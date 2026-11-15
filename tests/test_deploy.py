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
from http.server import ThreadingHTTPServer

from app import Handler


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
        print(state["version_endpoint"])
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
            "rollback_bad_http": False,
        }
        state_path = self.workspace / "state.json"

        class DeploymentHandler(Handler):
            def do_GET(self):
                if self.path != "/version":
                    return super().do_GET()
                state = json.loads(state_path.read_text())
                rollback = state.get("rollback", False)
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

        server = ThreadingHTTPServer(("127.0.0.1", 0), DeploymentHandler)
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
        self.state.update(candidate_bad_http=True, version_endpoint="")
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

    def test_invalid_or_mismatched_source_fails_before_docker(self):
        for sha in ("short", "c" * 40):
            with self.subTest(sha=sha):
                result, calls = self.deploy(GITHUB_SHA=sha)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(calls, [])
