import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_agent_sandbox as sandbox


class AgentSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.workspace = self.repo / "agent-workspaces" / "run_new" / "task"
        (self.workspace / "repo").mkdir(parents=True)
        (self.workspace / "PROBLEM.md").write_text("task\n")
        (self.repo / "benchmark-manifest.json").write_text("secret\n")
        self.task_dir = self.repo / "runs" / "run_new" / "tasks" / "task"

    def test_profile_denies_benchmark_control_and_allows_task_workspace(self):
        profile = sandbox.profile_for(self.workspace, self.repo)
        self.assertIn(f'(deny file-read* (subpath "{self.repo.resolve()}"))', profile)
        self.assertIn(f'(allow file-read* (subpath "{self.workspace.resolve()}"))', profile)

    def test_agent_probe_must_deny_control_read(self):
        with patch.object(sandbox.platform, "system", return_value="Darwin"), \
             patch.object(sandbox.subprocess, "run", side_effect=lambda cmd, **_: subprocess.CompletedProcess(cmd, 0)):
            with self.assertRaisesRegex(RuntimeError, "AGENT_GOLD_ISOLATION_NOT_PROVEN"):
                sandbox.prove_sandbox(self.workspace, self.task_dir, self.repo)
        proof = json.loads((self.task_dir / "agent-sandbox-proof.json").read_text())
        self.assertEqual(proof["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
