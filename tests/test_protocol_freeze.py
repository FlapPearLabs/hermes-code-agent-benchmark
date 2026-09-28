import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_protocol_freeze as freeze
from scripts.verify_protocol_freeze import PINNED_FILES, HARNESS_FILES, FreezeError, verify_freeze


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class ProtocolFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@localhost")
        self.config = self.repo.parent / (self.repo.name + ".sut-config")
        self.config.write_text("approval: off\n")
        self.addCleanup(self.config.unlink)
        hashes = {}
        for name in PINNED_FILES + HARNESS_FILES:
            if name == "PROTOCOL_V2.json":
                continue
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(name + "\n")
            hashes[name] = hashlib.sha256((self.repo / name).read_bytes()).hexdigest()
        self.protocol = {
            "protocol_tag": "benchmark/protocol-v2-test",
            "max_turns": 60,
            "approval_mode": "off",
            "yolo_mode": True,
            "hermes_version": "test-hermes",
            "file_sha256": hashes,
            "external_sha256": {
                "code_profile_config": {
                    "path": str(self.config),
                    "sha256": hashlib.sha256(self.config.read_bytes()).hexdigest(),
                }
            },
            "external_git": {},
        }
        (self.repo / "PROTOCOL_V2.json").write_text(json.dumps(self.protocol))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "protocol freeze")
        git(self.repo, "tag", "-a", self.protocol["protocol_tag"], "-m", "frozen")
        real_command = freeze.command
        def command(args, *, cwd):
            if args == ["hermes", "--version"]:
                return "test-hermes"
            return real_command(args, cwd=cwd)
        command_patch = patch.object(freeze, "command", side_effect=command)
        command_patch.start()
        self.addCleanup(command_patch.stop)

    def test_committed_tagged_protocol_passes_local_gate(self):
        self.assertEqual(verify_freeze("run_new", self.repo, check_remote=False)["status"], "PASS")

    def test_missing_protocol_tag_blocks_run(self):
        git(self.repo, "tag", "-d", self.protocol["protocol_tag"])
        with self.assertRaises(FreezeError):
            verify_freeze("run_new", self.repo, check_remote=False)

    def test_sut_config_drift_blocks_run(self):
        self.config.write_text("approval: changed\n")
        with self.assertRaisesRegex(FreezeError, "SUT_CONFIG_DRIFT"):
            verify_freeze("run_new", self.repo, check_remote=False)


if __name__ == "__main__":
    unittest.main()
