import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import export_candidate_patch as exporter
from scripts import prepare_agent_workspace as preparer


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class WorkspacePatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = "calibration_test"
        self.task_id = "sample-task"
        self.wrapper = self.root / "agent-workspaces" / self.run_id / self.task_id
        self.repo = self.wrapper / "repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@localhost")
        git(self.repo, "remote", "add", "origin", "https://github.com/example/repo.git")
        (self.repo / "tracked.txt").write_text("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.evidence = self.root / "runs" / self.run_id / "tasks" / self.task_id
        self.evidence.mkdir(parents=True)
        self.manifest = {
            "task_id": self.task_id, "run_id": self.run_id,
            "repo_root": str(self.repo), "base_sha": self.base,
            "base_tree": git(self.repo, "rev-parse", "HEAD^{tree}"),
            "initial_head": self.base, "initial_status": "",
            "expected_repo": {"kind": "git", "repo": "example/repo"},
        }
        (self.evidence / "workspace-manifest.json").write_text(json.dumps(self.manifest))
        self.addCleanup(patch.stopall)
        patch.object(exporter, "WORKSPACES_ROOT", self.root / "agent-workspaces").start()
        patch.object(exporter, "RUNS_ROOT", self.root / "runs").start()

    def test_untracked_new_file_is_exported(self):
        (self.repo / "new.txt").write_text("candidate\n")
        path = exporter.export_patch(self.task_id, self.run_id)
        self.assertIn(b"new file mode", path.read_bytes())
        self.assertIn(b"candidate", path.read_bytes())
        result = json.loads((self.evidence / "patch-export-result.json").read_text())
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["touched_paths"], ["new.txt"])

    def test_unrelated_head_is_base_divergence(self):
        git(self.repo, "checkout", "-q", "--orphan", "rogue")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "unrelated")
        with self.assertRaises(exporter.PatchExportError) as raised:
            exporter.export_patch(self.task_id, self.run_id)
        self.assertEqual(raised.exception.status, "BASE_DIVERGENCE")
        self.assertFalse((self.evidence / "patch.diff").exists())

    def test_whole_repository_change_is_rejected(self):
        for n in range(120):
            (self.repo / f"file-{n}.txt").write_text("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "larger base")
        self.manifest["base_sha"] = self.manifest["initial_head"] = git(self.repo, "rev-parse", "HEAD")
        self.manifest["base_tree"] = git(self.repo, "rev-parse", "HEAD^{tree}")
        (self.evidence / "workspace-manifest.json").write_text(json.dumps(self.manifest))
        for n in range(110):
            (self.repo / f"file-{n}.txt").write_text("changed\n")
        with self.assertRaises(exporter.PatchExportError) as raised:
            exporter.export_patch(self.task_id, self.run_id)
        self.assertEqual(raised.exception.status, "PATCH_EXPORT_INVALID")

    def test_prepare_requires_clean_base(self):
        manifest = {"calibration_tasks": [{
            "task_id": self.task_id, "track": "terminal-bench",
            "upstream_sha": "example", "instruction": "task"
        }], "scored_tasks": []}
        (self.root / "benchmark-manifest.json").write_text(json.dumps(manifest))
        new_run = "new_run"

        def fake_docker(task, repo):
            repo.mkdir(parents=True)
            git(repo, "init", "-q")
            (repo / "dirty.txt").write_text("untracked")
            return {"kind": "official_agent_image", "image_id": "example"}

        with patch.object(preparer, "REPO_DIR", self.root), \
             patch.object(preparer, "WORKSPACES_ROOT", self.root / "agent-workspaces"), \
             patch.object(preparer, "RUNS_ROOT", self.root / "runs"), \
             patch.object(preparer, "docker_workspace", side_effect=fake_docker):
            with self.assertRaisesRegex(RuntimeError, "DIRTY_BASE"):
                preparer.prepare_workspace(self.task_id, new_run)


if __name__ == "__main__":
    unittest.main()
