import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_protocol_freeze as freeze
from scripts.verify_protocol_freeze import (PINNED_FILES, HARNESS_FILES, FreezeError,
                                            _skill_tree_sha256, verify_freeze,
                                            verify_local_patch_set)


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

    def test_declared_local_patch_passes_and_undeclared_dirt_fails(self):
        runtime = self.repo / "runtime"
        runtime.mkdir()
        git(runtime, "init", "-q")
        git(runtime, "config", "user.name", "Test")
        git(runtime, "config", "user.email", "test@localhost")
        (runtime / "source.py").write_text("base\n")
        git(runtime, "add", "source.py")
        git(runtime, "commit", "-q", "-m", "base")
        head = git(runtime, "rev-parse", "HEAD")
        (runtime / "source.py").write_text("local patch\n")
        (runtime / "artifact.txt").write_text("generated\n")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        def diff_hash(*args):
            return hashlib.sha256(subprocess.run(
                ["git", "-C", str(runtime), *args], check=True,
                capture_output=True).stdout).hexdigest()
        manifest = {
            "schema_version": 1, "upstream_sha": head, "head_sha": head,
            "acceptance": "ACCEPTED_FOR_CALIBRATION",
            "accepted_provenance": {
                "PURPOSE": "test patch", "BASE_SHA": head,
                "DIFF_SHA256": diff_hash("diff", "--binary", "HEAD"),
                "AFFECTED_FILE": "source.py", "WHY_REQUIRED": "test fixture",
                "RUNTIME_EFFECT": "changed source", "VERIFICATION_EVIDENCE": ["fixture diff"],
            },
            "tracked_diff_sha256": diff_hash("diff", "--binary", "HEAD"),
            "staged_diff_sha256": diff_hash("diff", "--cached", "--binary", "HEAD"),
            "tracked_files": [{"path": "source.py", "sha256": digest(runtime / "source.py"),
                               "mode": "0644", "classification": "EXPECTED_LOCAL_PATCH",
                               "provenance": "owner approved"}],
            "untracked_files": [{"path": "artifact.txt", "sha256": digest(runtime / "artifact.txt"),
                                 "mode": "0644", "classification": "RUNTIME_GENERATED_ARTIFACT",
                                 "provenance": "generated by runtime"}],
        }
        path = self.repo / "runtime-manifest.json"
        path.write_text(json.dumps(manifest))
        self.assertEqual(verify_local_patch_set(runtime, path)["status"], "PASS")
        (runtime / "extra.txt").write_text("undeclared\n")
        with self.assertRaisesRegex(FreezeError, "SUT_UNDECLARED_DIRT"):
            verify_local_patch_set(runtime, path)
        (runtime / "extra.txt").unlink()
        manifest["tracked_files"][0]["classification"] = "UNKNOWN"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(FreezeError, "SUT_PATCH_UNACCEPTED"):
            verify_local_patch_set(runtime, path)

    def test_bundled_skill_source_requires_matching_active_copy(self):
        runtime = self.repo / "runtime"
        runtime.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Test"),
                     ("config", "user.email", "test@localhost")):
            git(runtime, *args)
        source = runtime / "source.py"
        source.write_text("base\n")
        git(runtime, "add", "source.py")
        git(runtime, "commit", "-q", "-m", "base")
        head = git(runtime, "rev-parse", "HEAD")
        source.write_text("patched\n")
        skill = runtime / "skills/productivity/example/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("example skill\n")
        profile = self.repo / "profile-skills"
        active = profile / "productivity/example/SKILL.md"
        active.parent.mkdir(parents=True)
        active.write_bytes(skill.read_bytes())
        skill_sha = hashlib.sha256(skill.read_bytes()).hexdigest()
        diff_sha = hashlib.sha256(subprocess.run(
            ["git", "-C", str(runtime), "diff", "--binary", "HEAD"],
            check=True, capture_output=True).stdout).hexdigest()
        owner = {"runtime_repo": str(runtime.resolve()), "canonical_profile_root": str(profile.resolve()),
                 "profile_skill_tree_sha256": _skill_tree_sha256(profile),
                 "redundant_copies_removed": 0, "files_remaining_unknown": 0,
                 "files": [{"RUNTIME_PATH": "skills/productivity/example/SKILL.md",
                            "CANONICAL_PROFILE_PATH": str(active.resolve()),
                            "SHA256_RUNTIME": skill_sha, "SHA256_CANONICAL": skill_sha,
                            "BYTE_IDENTICAL": True, "REFERENCED_BY_RUNTIME_CODE": True,
                            "SAFE_TO_REMOVE_FROM_RUNTIME_REPO": False,
                            "CLASSIFICATION": "CANONICAL_RUNTIME_DEPENDENCY"}]}
        (self.repo / "ownership.json").write_text(json.dumps(owner))
        manifest = {
            "schema_version": 1, "upstream_sha": head, "head_sha": head,
            "tracked_diff_sha256": diff_sha,
            "staged_diff_sha256": hashlib.sha256(b"").hexdigest(),
            "skill_ownership_manifest": "ownership.json",
            "acceptance": "ACCEPTED_FOR_CALIBRATION",
            "accepted_provenance": {"PURPOSE": "test", "BASE_SHA": head,
                                    "DIFF_SHA256": diff_sha, "AFFECTED_FILE": "source.py",
                                    "WHY_REQUIRED": "test", "RUNTIME_EFFECT": "test",
                                    "VERIFICATION_EVIDENCE": ["test"]},
            "tracked_files": [{"path": "source.py", "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                               "mode": "0644", "classification": "EXPECTED_LOCAL_PATCH",
                               "provenance": "test"}],
            "untracked_files": [{"path": "skills/productivity/example/SKILL.md",
                                 "sha256": skill_sha, "mode": "0644",
                                 "classification": "CANONICAL_RUNTIME_DEPENDENCY",
                                 "provenance": "bundled source"}],
        }
        path = self.repo / "runtime-manifest.json"
        path.write_text(json.dumps(manifest))
        self.assertEqual(verify_local_patch_set(runtime, path)["status"], "PASS")
        active.write_text("drift\n")
        with self.assertRaisesRegex(FreezeError, "SUT_SKILL_OWNERSHIP_DRIFT"):
            verify_local_patch_set(runtime, path)


if __name__ == "__main__":
    unittest.main()
