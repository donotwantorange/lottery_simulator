"""Permanent removal flow with synthetic snapshots; no Docker or host deletion."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = r'''
set -Eeuo pipefail
source scripts/manage.sh
project_dir=$PWD
stage=start
legacy_deleted=无
admin=()
management_admin() { admin=(); }
management_legacy_preflight() {
  printf 'preflight\n' >> "$LEGACY_CALLS"
  legacy_target_project=fixture
  legacy_proxy_subnet=172.30.96.0/24
  legacy_proxy_range=172.30.96.128/25
  legacy_proxy_gateway=172.30.96.1
  legacy_proxy_ip=172.30.96.2
  [[ ${LEGACY_PREFLIGHT_FAIL:-} != 1 ]]
}
management_legacy_context() { printf 'context\n' >> "$LEGACY_CALLS"; return 0; }
management_legacy_snapshot() {
  printf 'snapshot\n' >> "$LEGACY_CALLS"
  local count
  count=$(awk '$1=="snapshot" { n++ } END { print n+0 }' "$LEGACY_CALLS")
  if [[ $count == 2 && -n ${LEGACY_CHANGED:-} ]]; then printf '%s\n' "$LEGACY_CHANGED";
  else printf '%s\n' "$LEGACY_SNAPSHOT"; fi
}
management_private() { printf 'private:%s\n' "$1" >> "$LEGACY_CALLS"; [[ ${LEGACY_PRIVATE_FAIL:-} != "$1" ]]; }
deployment_check_timer() { timer_state=not-found; [[ ${LEGACY_TIMER_FAIL:-} != 1 ]]; }
management_legacy_cleared() { printf 'cleared\n' >> "$LEGACY_CALLS"; [[ ${LEGACY_CLEAR_FAIL:-} != 1 ]]; }
docker_cmd() {
  printf 'docker:%s\n' "$*" >> "$LEGACY_CALLS"
  if [[ $1 == stop || $1 == rm || $1 == network || $1 == volume ]]; then
    [[ -n ${!#} ]] || return 8
  fi
  [[ ${LEGACY_DOCKER_FAIL:-} != "$1 $2" ]]
}
bash() { printf 'install:%s\n' "$*" >> "$LEGACY_CALLS"; [[ ${LEGACY_INSTALL_FAIL:-} != 1 ]]; }
trap 'printf "FAILED phase=%s deleted=%s\n" "$stage" "$legacy_deleted"' ERR
management_legacy_run "$LEGACY_OUTCOME"
'''


class LegacyFlowTest(unittest.TestCase):
    def run_flow(self, answers, **flags):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "scripts").mkdir()
            for name in ("manage.sh", "deployment_checks.sh"):
                shutil.copy2(SOURCE / "scripts" / name, root / "scripts" / name)
            snapshot = {"project": "fixture", "containers": {"a" * 12: {}},
                        "networks": {"fixture_backend": {}},
                        "volumes": {"fixture_lottery_data": {}}}
            calls = root / "calls"
            env = {**os.environ, "LEGACY_CALLS": str(calls),
                   "LEGACY_SNAPSHOT": json.dumps(snapshot, sort_keys=True),
                   "LEGACY_OUTCOME": "reinstall", **flags}
            result = subprocess.run(["bash", "-c", SCRIPT], cwd=root, input=answers,
                                    capture_output=True, text=True, env=env)
            return result.returncode, result.stdout + result.stderr, calls.read_text().splitlines()

    def test_each_cancel_leaves_services_untouched(self):
        for answers in ("NO\n", "UNINSTALL\nNO\n"):
            code, output, calls = self.run_flow(answers)
            self.assertNotEqual(code, 0, output)
            self.assertFalse(any(c.startswith(("docker:stop", "docker:rm", "private:delete", "install:")) for c in calls))

    def test_confirmation_change_or_timer_failure_stops_before_service_change(self):
        changed = json.dumps({"project": "fixture", "containers": {}, "networks": {}, "volumes": {}}, sort_keys=True)
        for flag in ({"LEGACY_CHANGED": changed}, {"LEGACY_TIMER_FAIL": "1"}):
            code, output, calls = self.run_flow("UNINSTALL\nDELETE-fixture\n", **flag)
            self.assertNotEqual(code, 0, output)
            self.assertFalse(any(c.startswith(("docker:stop", "docker:rm", "private:delete")) for c in calls))

    def test_cleanup_order_and_fresh_install_only_after_clear(self):
        code, output, calls = self.run_flow("UNINSTALL\nDELETE-fixture\n")
        self.assertEqual(code, 0, output)
        expected = ["docker:stop --timeout 120 " + "a" * 12,
                    "docker:rm " + "a" * 12,
                    "docker:network rm fixture_backend", "docker:volume rm fixture_lottery_data",
                    "private:delete", "cleared"]
        positions = [next(i for i, item in enumerate(calls) if item.startswith(value)) for value in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(calls[-1].startswith("install:"))

    def test_failed_cleanup_or_clear_never_installs(self):
        for flag in ({"LEGACY_DOCKER_FAIL": "rm " + "a" * 12}, {"LEGACY_CLEAR_FAIL": "1"}):
            code, output, calls = self.run_flow("UNINSTALL\nDELETE-fixture\n", **flag)
            self.assertNotEqual(code, 0, output)
            self.assertFalse(any(c.startswith("install:") for c in calls))

    def test_install_failure_reports_completed_deletion_without_retry(self):
        code, output, calls = self.run_flow("UNINSTALL\nDELETE-fixture\n", LEGACY_INSTALL_FAIL="1")
        self.assertNotEqual(code, 0)
        self.assertIn("文件:", output)
        self.assertEqual(sum(c.startswith("install:") for c in calls), 1)
        self.assertEqual(sum(c.startswith("private:delete") for c in calls), 1)

    def test_independent_uninstall_does_not_install(self):
        code, output, calls = self.run_flow("UNINSTALL\nDELETE-fixture\n", LEGACY_OUTCOME="uninstall")
        self.assertEqual(code, 0, output)
        self.assertFalse(any(c.startswith("install:") for c in calls))

    def test_residual_and_empty_resource_groups_do_not_issue_empty_docker_targets(self):
        for containers, networks, volumes in (
            ({}, {"fixture_backend": {}}, {"fixture_lottery_data": {}}),
            ({"a" * 12: {}}, {}, {}),
        ):
            snapshot = {"project": "fixture", "containers": containers,
                        "networks": networks, "volumes": volumes}
            with self.subTest(snapshot=snapshot):
                code, output, calls = self.run_flow("UNINSTALL\nDELETE-fixture\n",
                    LEGACY_SNAPSHOT=json.dumps(snapshot, sort_keys=True), LEGACY_OUTCOME="uninstall")
                self.assertEqual(code, 0, output)
                self.assertFalse(any(c in {"docker:stop --timeout 120 ", "docker:rm ",
                                            "docker:network rm ", "docker:volume rm "} for c in calls))

    def test_real_clear_check_rejects_docker_read_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "scripts").mkdir()
            for name in ("manage.sh", "deployment_checks.sh"):
                shutil.copy2(SOURCE / "scripts" / name, root / "scripts" / name)
            shell = r'''
set -Eeuo pipefail
source scripts/manage.sh
docker_cmd() {
  if [[ $1 == ps ]]; then return 0; fi
  if [[ $1 == volume && $2 == ls ]]; then return 9; fi
  return 0
}
management_legacy_cleared fixture "$PWD"
'''
            result = subprocess.run(["bash", "-c", shell], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
