"""Run the deploy shell with a Docker test double and real host HTTP smoke."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from app import Handler, Server


ROOT = Path(__file__).resolve().parents[1]
LIVE_SHA = "b" * 40

# This models the external Docker boundary, not actual container execution.
DOCKER_DOUBLE = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
state_file = Path("state.json")
state = json.loads(state_file.read_text())
with open("docker.jsonl", "a") as log:
    log.write(json.dumps({"args": args, "sha": os.environ["GITHUB_SHA"],
                          "image": os.environ["DEVFLOW_IMAGE"]}) + "\n")
if args[0] == "compose":
    command = args[5]
    if command == "build" and state.get("build_fail"):
        raise SystemExit(23)
    if command == "up":
        rollback = os.environ["DEVFLOW_IMAGE"].endswith(":live")
        state["rollback"] = rollback
        state["runtime"] = os.environ["GITHUB_SHA"]
        state_file.write_text(json.dumps(state))
    elif command == "ps":
        print("container-id")
    elif command not in ("build", "logs"):
        raise SystemExit("unexpected compose command: " + repr(args))
elif args[0] == "inspect":
    print("true" if ".State.Running" in args[2] else "image-id")
elif args[:2] == ["image", "inspect"]:
    live = args[-1].endswith(":live") or state.get("rollback", False)
    if "--format" not in args:
        raise SystemExit(0 if state["has_live"] else 1)
    if "version-endpoint" in args[3]:
        print(state["version_endpoint"] if live else "1")
    elif "stats-endpoint" in args[3]:
        print(state["stats_endpoint"] if live else state["candidate_stats_endpoint"])
    else:
        print(state["live_sha"] if live else state["candidate_oci"])
elif args[0] != "tag":
    raise SystemExit("unexpected docker command: " + repr(args))
'''


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(self.enterContext(tempfile.TemporaryDirectory(prefix=".deploy-test-", dir=ROOT)))
        self.sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        self.state = {
            "candidate_oci": self.sha, "candidate_bad_http": False,
            "has_live": True, "live_sha": LIVE_SHA, "version_endpoint": "1",
            "rollback_bad_http": False, "stats_endpoint": "1", "candidate_stats_endpoint": "1",
            "candidate_bad_stats": False, "rollback_bad_stats": False,
        }
        state_path = self.workspace / "state.json"

        class DeploymentHandler(Handler):
            def do_GET(self):
                state = json.loads(state_path.read_text())
                rollback = state.get("rollback", False)
                legacy = rollback and state["stats_endpoint"] in ("", "<no value>")
                if self.path == "/" and legacy:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"hello devflow")
                    return
                if self.path == "/stats" and (legacy or state["rollback_bad_stats" if rollback else "candidate_bad_stats"]):
                    self.send_error(404)
                    return
                if self.path != "/version":
                    return super().do_GET()
                if rollback and state["version_endpoint"] in ("", "<no value>"):
                    self.send_error(404)
                    return
                bad = state["rollback_bad_http" if rollback else "candidate_bad_http"]
                body = json.dumps({"revision": "wrong" if bad else state["runtime"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = Server(("127.0.0.1", 0), DeploymentHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        (self.workspace / ".devflow").mkdir()
        (self.workspace / "deploy").mkdir()
        (self.workspace / "bin").mkdir()
        shutil.copy(ROOT / ".devflow/deploy.sh", self.workspace / ".devflow/deploy.sh")
        shutil.copy(ROOT / "smoke.py", self.workspace / "smoke.py")
        # Explicit verification boundary double: these tests prove orchestration,
        # not Docker or Chromium. Real browser evidence comes from Actions.
        verifier = self.workspace / ".devflow/verify.sh"
        verifier.write_text('''#!/usr/bin/env python3
import json, os
from pathlib import Path
state = json.loads(Path("state.json").read_text())
with open("verify.jsonl", "a") as log:
    log.write(json.dumps({k: os.environ[k] for k in (
        "GITHUB_SHA", "DEVFLOW_EXPECTED_REVISION", "DEVFLOW_VERSION_ENDPOINT",
        "DEVFLOW_STATS_ENDPOINT", "DEVFLOW_VERIFY_PHASE",
        "DEVFLOW_BASE_URL", "DEVFLOW_NET", "DEVFLOW_INNER_URL")}) + "\\n")
raise SystemExit(1 if state.get("verify_fail") and not state.get("rollback") else 0)
''')
        verifier.chmod(0o755)
        (self.workspace / '.devflow/capture.sh').write_text('exec python3 .devflow/capture-double.py "$@"\n')
        capture = self.workspace / '.devflow/capture-double.py'
        capture.write_text('''#!/usr/bin/env python3
import json, sys
from pathlib import Path
state = json.loads(Path('state.json').read_text())
with open('capture.jsonl', 'a') as log:
    log.write(json.dumps({'project': sys.argv[1], 'label': sys.argv[2], 'rollback': state.get('rollback', False)}) + '\\n')
raise SystemExit(42 if state.get('capture_fail') else 0)
''')
        config = (ROOT / ".devflow/config.env").read_text().replace("DEVFLOW_PORT=18100", f"DEVFLOW_PORT={server.server_port}")
        (self.workspace / ".devflow/config.env").write_text(config)
        docker = self.workspace / "bin/docker"
        docker.write_text(f"#!{sys.executable}\n" + DOCKER_DOUBLE)
        docker.chmod(0o755)

    def deploy(self, **env):
        (self.workspace / "state.json").write_text(json.dumps(self.state))
        result = subprocess.run(
            ["bash", ".devflow/deploy.sh"], cwd=self.workspace,
            env={**os.environ, "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
                 "GITHUB_SHA": self.sha, "DEVFLOW_REVISION": "stale-runner-value",
                 "GITHUB_STEP_SUMMARY": str(self.workspace / "summary"), **env},
            capture_output=True, text=True, timeout=15,
        )
        log = self.workspace / "docker.jsonl"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    def assert_rollback(self, result, calls):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        ups = [call for call in calls if call["args"][0] == "compose" and "up" in call["args"]]
        self.assertEqual([call["sha"] for call in ups], [self.sha, LIVE_SHA])
        self.assertTrue(ups[-1]["image"].endswith(":live"))
        self.assertIn("--no-build", ups[-1]["args"])
        self.assertFalse(any(call["args"][0] == "tag" for call in calls))

    def test_success_requires_http_and_oci_revision(self):
        result, calls = self.deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'"revision": "{self.sha}"', result.stdout)
        self.assertTrue(any(call["args"][0] == "tag" for call in calls))

    def test_browser_failure_rolls_back_without_marking_live(self):
        self.state["verify_fail"] = True
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn("devflow: rollback healthy", result.stderr)
        verifications = [json.loads(line) for line in (self.workspace / "verify.jsonl").read_text().splitlines()]
        self.assertEqual([v["DEVFLOW_EXPECTED_REVISION"] for v in verifications], [self.sha, LIVE_SHA])
        self.assertEqual([v["GITHUB_SHA"] for v in verifications], [self.sha, self.sha])
        self.assertTrue(all(v["DEVFLOW_NET"] == "devflow-devflow-smoke_default" for v in verifications))
        self.assertTrue(all(v["DEVFLOW_INNER_URL"] == "http://app:8080" for v in verifications))
        self.assertEqual([v["DEVFLOW_VERIFY_PHASE"] for v in verifications], ["candidate", "rollback"])
        self.assertEqual([v["DEVFLOW_STATS_ENDPOINT"] for v in verifications], ["1", "1"])

    def test_old_homepage_rollback_preserves_version_contract(self):
        self.state.update(verify_fail=True, stats_endpoint="")
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn("rollback healthy", result.stderr)
        self.assertIn("stats AC-1/AC-2 NOT verified", result.stdout)
        self.assertIn(f'"revision": "{LIVE_SHA}"', result.stdout)
        verifications = [json.loads(line) for line in (self.workspace / "verify.jsonl").read_text().splitlines()]
        self.assertEqual(verifications[-1]["DEVFLOW_STATS_ENDPOINT"], "")
        self.assertEqual(verifications[-1]["DEVFLOW_VERSION_ENDPOINT"], "1")

    def test_broken_candidate_stats_cannot_downgrade(self):
        self.state.update(candidate_bad_stats=True, stats_endpoint="")
        result, calls = self.deploy(DEVFLOW_STATS_ENDPOINT="", DEVFLOW_VERSION_ENDPOINT="", DEVFLOW_VERIFY_PHASE="rollback")
        self.assert_rollback(result, calls)
        self.assertIn("HTTP contract mismatch for /stats", result.stderr)
        self.assertIn("rollback healthy", result.stderr)

    def test_stats_capable_rollback_cannot_skip_broken_stats(self):
        self.state.update(candidate_bad_http=True, rollback_bad_stats=True)
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn("rollback also unhealthy", result.stderr)
        self.assertNotIn("stats AC-1/AC-2 NOT verified", result.stdout)

    def test_candidate_requires_stats_oci_label(self):
        self.state.update(candidate_stats_endpoint="")
        result, calls = self.deploy()
        self.assert_rollback(result, calls)

    def test_unknown_or_inconsistent_rollback_capabilities_fail_closed(self):
        for stats, version in (("2", "1"), ("1", ""), ("", "2")):
            with self.subTest(stats=stats, version=version):
                self.state.update(candidate_bad_http=True, stats_endpoint=stats, version_endpoint=version)
                log = self.workspace / "docker.jsonl"
                log.write_text("")
                result, calls = self.deploy()
                self.assertEqual(result.returncode, 1)
                self.assertFalse(any(call["args"][0] == "compose" and call["image"].endswith(":live") for call in calls))

    def test_legacy_rollback_journey_uses_old_contract(self):
        self.state.update(verify_fail=True, version_endpoint="", stats_endpoint="")
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        verifications = [json.loads(line) for line in (self.workspace / "verify.jsonl").read_text().splitlines()]
        self.assertEqual(verifications[-1]["DEVFLOW_VERSION_ENDPOINT"], "")
        self.assertEqual(verifications[-1]["DEVFLOW_EXPECTED_REVISION"], LIVE_SHA)

    def test_wrong_runtime_rolls_back_with_live_revision_but_exits_failure(self):
        self.state["candidate_bad_http"] = True
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn("devflow: rollback healthy", result.stderr)
        self.assertIn(f'"revision": "{LIVE_SHA}"', result.stdout)

    def test_wrong_oci_rolls_back(self):
        self.state["candidate_oci"] = "c" * 40
        result, calls = self.deploy()
        self.assert_rollback(result, calls)

    def test_legacy_rollback_explicitly_does_not_verify_version(self):
        self.state.update(candidate_bad_http=True, version_endpoint="", stats_endpoint="")
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn("/version NOT verified", result.stdout)
        self.assertIn("devflow: rollback healthy", result.stderr)

    def test_modern_rollback_cannot_skip_broken_version(self):
        self.state.update(candidate_bad_http=True, rollback_bad_http=True)
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn("rollback also unhealthy", result.stderr)
        self.assertNotIn("/version NOT verified", result.stdout)

    def test_invalid_live_revision_does_not_restart_old_image(self):
        self.state.update(candidate_bad_http=True, live_sha="short")
        result, calls = self.deploy()
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid rollback OCI revision", result.stderr)
        self.assertFalse(any(call["args"][0] == "compose" and call["image"].endswith(":live") for call in calls))

    def test_first_failed_deployment_has_no_rollback(self):
        self.state.update(candidate_bad_http=True, has_live=False)
        result, calls = self.deploy()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(call["args"][0] == "compose" and call["image"].endswith(":live") for call in calls))

    def test_capture_failure_does_not_mask_candidate_or_rollback(self):
        self.state.update(verify_fail=True, capture_fail=True)
        result, calls = self.deploy()
        self.assert_rollback(result, calls)
        self.assertIn('rollback healthy', result.stderr)
        captures = [json.loads(line) for line in (self.workspace / 'capture.jsonl').read_text().splitlines()]
        self.assertEqual([c['label'] for c in captures], ['candidate', 'rollback'])
        self.assertEqual([c['rollback'] for c in captures], [False, True])
        self.assertTrue(all(c['project'] == 'devflow-devflow-smoke' for c in captures))

    def test_build_failure_captures_without_changing_running_version(self):
        self.state.update(build_fail=True, capture_fail=True)
        result, calls = self.deploy()
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertFalse(any('up' in c['args'] or c['args'][0] == 'tag' for c in calls))
        capture = json.loads((self.workspace / 'capture.jsonl').read_text())
        self.assertEqual(capture['label'], 'build-failed')

    def test_invalid_or_mismatched_source_fails_before_docker(self):
        for sha in ("short", "c" * 40):
            with self.subTest(sha=sha):
                result, calls = self.deploy(GITHUB_SHA=sha)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(calls, [])
