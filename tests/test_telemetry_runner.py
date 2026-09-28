import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import chunked_benchmark_runner as runner
from scripts import collect_telemetry as telemetry


def stream_lines(*events):
    return "".join(json.dumps(event) + "\n" for event in events)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch_root = patch.object(telemetry, "RUNS_ROOT", self.root / "runs")
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.collector = telemetry.TaskTelemetryCollector("task-a", "test-run")
        self.stdout = self.collector.task_dir / "hermes-stream.jsonl"
        self.stderr = self.collector.task_dir / "hermes-stderr.log"
        self.stderr.write_text("diagnostic\n")

    def test_real_stream_events_drive_usage_and_duration(self):
        self.stdout.write_text(stream_lines(
            {"type": "system", "subtype": "init", "model": "model-a", "session_id": "session-a"},
            {"type": "tool_use", "name": "terminal", "tool_call_id": "one", "input": {"command": "true"}},
            {"type": "tool_result", "name": "terminal", "tool_call_id": "one", "is_error": False},
            {"type": "tool_use", "name": "skill_view", "tool_call_id": "two"},
            {"type": "tool_use", "name": "mcp__server__lookup", "tool_call_id": "three"},
            {"type": "tool_use", "name": "kanban_show", "tool_call_id": "four"},
            {"type": "result", "session_id": "session-a", "exit_code": 0,
             "tokens": {"input": 12, "output": 7, "total": 19, "cache_read": 0, "cache_write": 0}},
        ))
        summary = self.collector.ingest_stream(self.stdout, self.stderr, exit_code=0, duration_ms=2500)
        self.assertEqual(summary["trace_status"], "COMPLETE")
        self.assertEqual(summary["duration_ms"], 2500)
        self.assertEqual(summary["tokens"]["total"], 19)
        self.assertEqual(summary["tool_usage"]["status"], "USED")
        self.assertEqual(summary["skill_usage"]["status"], "USED")
        self.assertEqual(summary["mcp_usage"]["status"], "USED")
        self.assertEqual(summary["kanban_usage"]["status"], "USED")
        self.assertEqual(summary["goal_usage"]["status"], "TELEMETRY_UNAVAILABLE")
        self.assertEqual(summary["review_usage"]["status"], "TELEMETRY_UNAVAILABLE")
        self.assertEqual(json.loads((self.collector.task_dir / "tool-usage.json").read_text())["count"], 4)
        self.assertEqual(self.stdout.read_text().count("\n"), 7)

    def test_complete_stream_with_no_calls_is_not_used_but_zero_tokens_are_unavailable(self):
        self.stdout.write_text(stream_lines(
            {"type": "system", "subtype": "init", "session_id": "session-a"},
            {"type": "result", "session_id": "session-a", "exit_code": 0,
             "tokens": {"input": 0, "output": 0, "total": 0, "cache_read": 0, "cache_write": 0}},
        ))
        summary = self.collector.ingest_stream(self.stdout, self.stderr, exit_code=0, duration_ms=5)
        for key in ("tool_usage", "skill_usage", "mcp_usage", "kanban_usage"):
            self.assertEqual(summary[key]["status"], "NOT_USED")
        self.assertEqual(summary["tokens"], "NOT_AVAILABLE")

    def test_incomplete_stream_does_not_claim_not_used(self):
        self.stdout.write_text(stream_lines({"type": "system", "subtype": "init", "session_id": "session-a"}))
        summary = self.collector.ingest_stream(self.stdout, self.stderr, exit_code=1, duration_ms=5)
        self.assertEqual(summary["trace_status"], "TELEMETRY_UNAVAILABLE")
        self.assertEqual(summary["tokens"], "NOT_AVAILABLE")
        for key in ("tool_usage", "skill_usage", "mcp_usage", "goal_usage", "kanban_usage", "review_usage"):
            self.assertEqual(summary[key]["status"], "TELEMETRY_UNAVAILABLE")

    def test_result_exit_mismatch_is_telemetry_unavailable(self):
        self.stdout.write_text(stream_lines(
            {"type": "system", "subtype": "init", "session_id": "session-a"},
            {"type": "result", "session_id": "session-a", "exit_code": 0},
        ))
        summary = self.collector.ingest_stream(self.stdout, self.stderr, exit_code=1, duration_ms=5)
        self.assertEqual(summary["trace_status"], "TELEMETRY_UNAVAILABLE")
        self.assertEqual(summary["tool_usage"]["status"], "TELEMETRY_UNAVAILABLE")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.joinpath("scripts").mkdir()
        for module, name, value in (
            (runner, "REPO_DIR", self.root),
            (runner, "SCRIPTS_DIR", self.root / "scripts"),
            (runner, "PYTHON_BIN", Path("/python")),
            (runner, "MANIFEST_PATH", self.root / "benchmark-manifest.json"),
            (runner, "STATE_PATH", self.root / "runs" / "state.json"),
            (telemetry, "RUNS_ROOT", self.root / "runs"),
        ):
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_scored_stage_is_rejected_without_starting_any_task(self):
        with patch.object(runner.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                runner.main(["--run-id", "new-run", "--stage", "scored"])
            run.assert_not_called()

    def test_run_id_cannot_escape_runs_directory(self):
        with patch.object(runner.subprocess, "run") as run:
            with self.assertRaises(SystemExit):
                runner.main(["--run-id", "../outside", "--stage", "calibration"])
            run.assert_not_called()

    def test_direct_script_help_loads_without_project_package_on_sys_path(self):
        script = Path(runner.__file__)
        result = subprocess.run([sys.executable, str(script), "--help"], cwd=self.root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--stage {calibration}", result.stdout)

    def test_calibration_stage_does_not_dispatch_scored_tasks(self):
        self.root.joinpath("benchmark-manifest.json").write_text(json.dumps({
            "calibration_tasks": [{"task_id": "calib"}],
            "scored_tasks": [{"task_id": "scored"}],
        }))
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
             patch.object(runner, "run_single_task", return_value={"status": "GRADER_EVIDENCE_UNVERIFIED"}) as task:
            with self.assertRaisesRegex(RuntimeError, "Calibration evidence is not valid"):
                runner.main(["--run-id", "new-run", "--stage", "calibration"])
        self.assertEqual(task.call_count, 1)
        self.assertEqual(task.call_args.args[0]["task_id"], "calib")
        self.assertIn("verify_protocol_freeze.py", " ".join(map(str, run.call_args.args[0])))
        state = json.loads((self.root / "runs" / "new-run" / "runner-state.json").read_text())
        self.assertEqual(state["status"], "CALIBRATION_FAILED")

    def test_protocol_preflight_failure_stops_before_workspace_preparation(self):
        self.root.joinpath("benchmark-manifest.json").write_text(json.dumps({"calibration_tasks": [{"task_id": "one"}]}))
        with patch.object(runner.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "verify")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                runner.main(["--run-id", "new-run", "--stage", "calibration"])
        self.assertEqual(len(run.call_args_list), 1)
        self.assertIn("verify_protocol_freeze.py", " ".join(map(str, run.call_args.args[0])))

    def test_unsupported_terminal_state_blocks_entire_calibration_before_task_start(self):
        self.root.joinpath("benchmark-manifest.json").write_text(json.dumps({
            "calibration_tasks": [
                {"task_id": "swe", "track": "swe-bench-verified"},
                {"task_id": "terminal", "track": "terminal-bench"}],
        }))
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(runner, "run_single_task") as task:
            with self.assertRaisesRegex(RuntimeError, "UNSUPPORTED_STATE"):
                runner.main(["--run-id", "new-run", "--stage", "calibration"])
        task.assert_not_called()
        self.assertFalse((self.root / "runs" / "new-run").exists())

    def test_nonzero_hermes_exit_persists_raw_trace_then_stops(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if any("prepare_agent_workspace.py" in str(part) for part in cmd):
                self.root.joinpath("agent-workspaces", "new-run", "one", "repo").mkdir(parents=True)
                return subprocess.CompletedProcess(cmd, 0)
            if cmd[0] == "hermes":
                kwargs["stdout"].write(stream_lines({"type": "system", "subtype": "init", "session_id": "s"}))
                kwargs["stderr"].write("agent failed\n")
                return subprocess.CompletedProcess(cmd, 2)
            return subprocess.CompletedProcess(cmd, 0)

        with patch.object(runner.subprocess, "run", side_effect=fake_run), \
             patch.object(runner, "prove_sandbox", return_value=[]), \
             patch.object(runner.time, "monotonic", side_effect=[9.0, 10.0, 12.5, 12.5]):
            with self.assertRaises(RuntimeError):
                runner.run_single_task({"task_id": "one"}, "calibration", run_id="new-run")
        task_dir = self.root / "runs" / "new-run" / "tasks" / "one"
        self.assertIn("agent failed", (task_dir / "hermes-stderr.log").read_text())
        self.assertIn('"type": "system"', (task_dir / "hermes-stream.jsonl").read_text())
        self.assertEqual(json.loads((task_dir / "hermes-process.json").read_text())["duration_ms"], 2500)
        self.assertEqual(json.loads((task_dir / "hermes-process.json").read_text())["exit_code"], 2)
        hermes_cmd = next(cmd for cmd in calls if cmd[0] == "hermes")
        self.assertEqual(hermes_cmd[hermes_cmd.index("--max-turns") + 1], "60")
        self.assertEqual(hermes_cmd[hermes_cmd.index("--format") + 1], "stream-json")
        self.assertFalse(any("export_candidate_patch.py" in " ".join(map(str, cmd)) for cmd in calls))


if __name__ == "__main__":
    unittest.main()
