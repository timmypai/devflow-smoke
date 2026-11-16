#!/usr/bin/env python3
"""Stdlib unittest entrypoint with exact-file selection and P2-compatible JUnit.

JUnit names are method names (not unittest's full dotted id) so check.py can
resolve path::test_method_name. A report never replaces unittest's exit status.
"""
import inspect
import os
from pathlib import Path
import sys
import time
import traceback
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class JUnitResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.started = {}
        self.recorded = set()

    def startTest(self, test):
        super().startTest(test)
        self.started[id(test)] = time.monotonic()

    def record(self, test, kind=None, detail='', *, parent=None):
        owner = parent if parent is not None else test
        name = getattr(owner, '_testMethodName', owner.id())
        if parent is not None:
            name += '[' + test._subDescription() + ']'
        case = ET.Element('testcase', name=name,
                          classname=owner.__class__.__module__ + '.' + owner.__class__.__qualname__,
                          time=f'{time.monotonic() - self.started.get(id(owner), time.monotonic()):.6f}')
        source = inspect.getsourcefile(owner.__class__)
        if source:
            try:
                case.set('file', str(Path(source).resolve().relative_to(ROOT)))
            except ValueError:
                pass
        if kind:
            ET.SubElement(case, kind, message=detail.splitlines()[-1] if detail else kind).text = detail
        self.cases.append(case)
        self.recorded.add(id(owner))

    def addSuccess(self, test):
        super().addSuccess(test)
        if id(test) not in self.recorded:
            self.record(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, 'failure', ''.join(traceback.format_exception(*err)))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, 'error', ''.join(traceback.format_exception(*err)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, 'skipped', reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, 'skipped', 'expected failure: ' + ''.join(traceback.format_exception(*err)))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, 'failure', 'unexpected success')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        kind = None if err is None else ('failure' if err[0] is not None and issubclass(err[0], test.failureException) else 'error')
        self.record(subtest, kind, '' if err is None else ''.join(traceback.format_exception(*err)), parent=test)

    def write_junit(self, destination):
        suite = ET.Element('testsuite', name='unittest', tests=str(len(self.cases)),
                           failures=str(sum(c.find('failure') is not None for c in self.cases)),
                           errors=str(sum(c.find('error') is not None for c in self.cases)),
                           skipped=str(sum(c.find('skipped') is not None for c in self.cases)))
        suite.extend(self.cases)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(suite).write(path, encoding='utf-8', xml_declaration=True)


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    selector = os.environ.get('DEVFLOW_TEST_ONLY', '')
    if selector:
        target = Path(selector)
        if (target.is_absolute() or '..' in target.parts or any(c in selector for c in '*?[')
                or target.suffix != '.py' or not target.is_file()
                or not target.resolve().is_relative_to(ROOT / 'tests')):
            print('DEVFLOW_TEST_ONLY must name one existing Python file under tests/', file=sys.stderr)
            return 2
        suite = loader.discover(str(target.parent), pattern=target.name)
    else:
        suite = loader.discover('tests')
    if suite.countTestCases() == 0:
        print('No tests discovered; refusing a vacuous success', file=sys.stderr)
        return 2
    result = unittest.TextTestRunner(verbosity=2, resultclass=JUnitResult).run(suite)
    assert isinstance(result, JUnitResult)
    destination = os.environ.get('DEVFLOW_JUNIT')
    if destination:
        result.write_junit(destination)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
