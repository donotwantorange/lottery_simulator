"""Resource ownership checks use only temporary files and synthetic Docker output."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from scripts.deployment_resources import InventoryError, inventory, check_private_tree


class ResourceInventoryTest(unittest.TestCase):
    def fixture(self, root, *, containers=True, service="worker", shared=False,
                foreign_bind=False, read_failure=False):
        cid = "a" * 64
        foreign = "c" * 64
        nid = "b" * 64
        project = "fixture"
        volume = "fixture_lottery_data"
        network = "fixture_backend"
        config = {"name": project, "volumes": {"lottery_data": {"name": volume}},
                  "networks": {"backend": {"name": network}}}
        owned = {"Id": cid, "Name": "/fixture-worker", "Config": {"Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.project.working_dir": str(root),
            "com.docker.compose.service": service}},
            "Mounts": [{"Type": "volume", "Name": volume, "Destination": "/app/data"}],
            "NetworkSettings": {"Networks": {network: {}}}}
        if foreign_bind:
            owned["Mounts"].append({"Type": "bind", "Source": "/var/lib/unknown",
                                    "Destination": "/unknown"})
        outsider = {"Id": foreign, "Config": {"Labels": {}},
                    "Mounts": [{"Type": "volume", "Name": volume}] if shared else [],
                    "NetworkSettings": {"Networks": {}}}
        replies = {
            ("compose", "config", "--format", "json"): config,
            ("ps", "-aq"): [cid, foreign] if containers else [],
            ("inspect", cid): [owned], ("inspect", foreign): [outsider],
            ("volume", "ls", "-q", "--filter", "label=com.docker.compose.project=fixture"): [volume],
            ("volume", "inspect", volume): [{"Name": volume, "Labels": {
                "com.docker.compose.project": project, "com.docker.compose.volume": "lottery_data"}}],
            ("network", "ls", "-q", "--filter", "label=com.docker.compose.project=fixture"): [nid],
            ("network", "inspect", nid): [{"Id": nid, "Name": network, "Labels": {
                "com.docker.compose.project": project, "com.docker.compose.network": "backend"},
                "Containers": {cid: {}} if containers else {}}],
        }
        def run(command, **_):
            args = tuple(command[1:])
            if read_failure and args == ("ps", "-aq"):
                return subprocess.CompletedProcess(command, 1, "", "unavailable")
            answer = replies[args]
            output = "\n".join(answer) if isinstance(answer, list) and all(isinstance(x, str) for x in answer) else json.dumps(answer)
            return subprocess.CompletedProcess(command, 0, output, "")
        return run

    def test_different_service_layout_and_missing_old_image_are_irrelevant(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); (root / ".env").write_text("old")
            result = inventory(root, run=self.fixture(root, service="legacy-worker"), backup_parent=root / "backup")
            self.assertEqual(list(result["containers"].values())[0]["service"], "legacy-worker")
            self.assertEqual(list(result["volumes"]), ["fixture_lottery_data"])

    def test_residual_labeled_resources_need_local_compose_declaration(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); (root / ".env").write_text("old")
            result = inventory(root, run=self.fixture(root, containers=False), backup_parent=root / "backup")
            self.assertEqual(result["containers"], {})
            self.assertEqual(list(result["networks"]), ["fixture_backend"])

    def test_shared_bind_and_read_failure_refuse_inventory(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); (root / ".env").write_text("old")
            for flags in ({"shared": True}, {"foreign_bind": True}, {"read_failure": True}):
                with self.subTest(flags=flags), self.assertRaises(InventoryError):
                    inventory(root, run=self.fixture(root, **flags), backup_parent=root / "backup")

    def test_env_or_backup_change_alters_confirmation_snapshot(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); (root / ".env").write_text("old")
            backup = root / "backup" / "fixture"; backup.mkdir(parents=True)
            run = self.fixture(root)
            before = inventory(root, run=run, backup_parent=root / "backup")
            (root / ".env").write_text("new")
            (backup / "new.sqlite3").write_text("backup")
            after = inventory(root, run=run, backup_parent=root / "backup")
            self.assertNotEqual(before, after)

    def test_private_tree_rejects_root_and_child_mounts_including_escaped_paths(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "backup tree"; root.mkdir()
            child = root / "nested"; child.mkdir()
            (child / "snapshot").write_text("fixture")
            empty_mounts = "1 0 0:1 / / rw - ext4 /dev/sda rw\n"
            self.assertIn("nested/snapshot", check_private_tree(root, empty_mounts))
            for target in (root, child):
                escaped = str(target).replace(" ", r"\040")
                mountinfo = empty_mounts + f"2 1 0:1 / {escaped} rw - ext4 /dev/sda rw\n"
                with self.subTest(target=target), self.assertRaises(InventoryError):
                    check_private_tree(root, mountinfo)
            with self.assertRaises(InventoryError):
                check_private_tree(root, "malformed mountinfo\n")


if __name__ == "__main__":
    unittest.main()
