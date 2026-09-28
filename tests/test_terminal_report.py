"""A Terminal-Bench candidate must be reportable without borrowing the patch track's vocabulary.

The report gate decides EXECUTED/RESOLVED from evidence that was written for git
patch candidates: a ``patch.diff`` whose digest is recomputed at report time and an
``APPLIED`` install status. A sandbox-state candidate carries a recorded artifact
tree instead, so before it could be represented at all the only way to pass those
gates was to write the patch track's labels onto it. These tests pin the honest
shape: a per-artifact-type install vocabulary, an identity digest recomputed from
the recorded trial, and a report that can actually count a passing terminal task.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_report
import candidate_artifact
import fresh_sandbox_regrade
import terminal_replay as tr


TASK_ID = "terminal-cal-01"
TRIAL_ID = "candidate-trial-id"


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _fixture(tmp_path, monkeypatch):
    scored = [{"task_id": f"scored-{i:02d}", "track": "swe-bench-verified",
               "is_calibration": False} for i in range(20)]
    calibration = [{"task_id": TASK_ID, "track": "terminal-bench",
                    "is_calibration": True}]
    _write_json(tmp_path / "benchmark-manifest.json", {
        "scored_tasks": scored, "calibration_tasks": calibration})
    monkeypatch.setattr(build_report, "MANIFEST_PATH", tmp_path / "benchmark-manifest.json")
    monkeypatch.setattr(build_report, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(build_report, "REPORTS_DIR", tmp_path / "reports")
    return tmp_path / "runs" / "run_test"


def _candidate_trial(task_dir):
    """A recorded source trial carrying the collected artifact tree."""
    trial = task_dir / "trials" / "candidate-job" / "trial-0"
    (trial / "artifacts" / "app" / "src").mkdir(parents=True)
    (trial / "artifacts" / "app" / "src" / "worker.py").write_text("state\n")
    (trial / "artifacts" / "manifest.json").write_text("[]\n")
    return trial


def _terminal_task(task_dir, *, status="PASS", install="SEEDED", phase_process=True):
    """The evidence the runner and the official regrade path write for a terminal task."""
    task_dir.mkdir(parents=True, exist_ok=True)
    trial = _candidate_trial(task_dir)
    state_sha = tr.candidate_state_sha256(trial)
    _write_json(task_dir / "trial-export-result.json", {
        "status": "VALID", "task_id": TASK_ID, "run_id": "run_test",
        "candidate_artifact_type": "SANDBOX_STATE",
        "candidate_trial_dir": str(trial), "trial_id": TRIAL_ID,
        "candidate_state_sha256": state_sha})
    for prefix, identity, raw in (("grader", "trial-grader", "official-trials/t1/result.json"),
                                  ("fresh-sandbox", "trial-fresh", "official-trials/t2/result.json")):
        raw_path = task_dir / raw
        _write_json(raw_path, {"verifier_result": {"rewards": {"reward": 1}}})
        _write_json(task_dir / f"{prefix}-result.json", {
            "task_id": TASK_ID, "run_id": "run_test", "status": status,
            "resolved": status == "PASS",
            "official_grader_process_started": phase_process,
            "official_grader_executed": phase_process,
            "official_grader_process_proven": True,
            "official_grader_agent_phase": "NOT_EXECUTED",
            "replay_agent_phase_executed": False,
            "candidate_artifact_type": "SANDBOX_STATE",
            "candidate_patch_sha256": state_sha,
            "patch_apply_status": install, "grader_exit_code": 0,
            "grader_duration_ms": 12, "sandbox_identity": identity,
            "sandbox_identity_kind": "harbor_trial_id",
            "raw_result_path": str(raw_path)})
        _write_json(task_dir / f"{prefix}-command.json",
                    {"argv": ["harbor", "trials", "regrade"], "cwd": str(task_dir)})
        _write_json(task_dir / f"{prefix}-env.json", {"PATH": "/bin"})
        (task_dir / f"{prefix}-exit-code.txt").write_text("0\n")
        (task_dir / f"{prefix}-stdout.log").write_text("regraded\n")
        (task_dir / f"{prefix}-stderr.log").write_text("")
    return task_dir, trial, state_sha


def _fresh_regrade(task_dir, task, state_sha, *, install="SEEDED"):
    grader = json.loads((task_dir / "fresh-sandbox-result.json").read_text())
    result = fresh_sandbox_regrade.build_fresh_result(TASK_ID, task, state_sha, grader)
    _write_json(task_dir / "fresh-regrade-result.json", result)
    return result


# ---------------------------------------------------------------------------
# one vocabulary, per artifact type
# ---------------------------------------------------------------------------

def test_install_vocabulary_is_defined_per_artifact_type():
    assert candidate_artifact.expected_install_status("GIT_PATCH") == "APPLIED"
    assert candidate_artifact.expected_install_status("SANDBOX_STATE") == "SEEDED"
    assert candidate_artifact.expected_install_status(
        candidate_artifact.artifact_type("terminal-bench")) == "SEEDED"
    with pytest.raises(ValueError, match="UNKNOWN_CANDIDATE_ARTIFACT_TYPE"):
        candidate_artifact.expected_install_status("MADE_UP")


def test_replay_evidence_names_the_seeded_install_and_no_agent_phase(tmp_path, monkeypatch):
    """The replay record must not borrow the patch track's APPLIED label."""
    _, _, task_dir, source = _layout(tmp_path)
    trial = _replay_trial(tmp_path, source)
    evidence = tr.read_replay_evidence(
        task_id="payments-pipeline-fix", trial_dir=trial, exit_code=0,
        source_trial_dir=source, source_trial_id="source-id",
        source_stream_sha256=hashlib.sha256(_STREAM).hexdigest(),
        candidate_state_sha256_value=tr.candidate_state_sha256(source))
    assert evidence["patch_apply_status"] == "SEEDED"
    assert evidence["candidate_artifact_type"] == "SANDBOX_STATE"
    assert evidence["official_grader_agent_phase"] == "NOT_EXECUTED"
    assert evidence["replay_agent_phase_executed"] is False
    assert "official_grader_agent" not in evidence


def test_fresh_result_maps_install_status_to_the_artifact_type(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir(parents=True)
    task = {"task_id": TASK_ID, "track": "terminal-bench"}
    grader = {"status": "PASS", "resolved": True, "patch_apply_status": "SEEDED",
              "sandbox_identity": "trial-fresh", "grader_exit_code": 0,
              "official_grader_executed": True}
    result = fresh_sandbox_regrade.build_fresh_result(TASK_ID, task, "d" * 64, grader)
    assert result["candidate_installed"] is True
    assert result["patch_apply_status"] == "SEEDED"
    assert result["resolved"] is True
    assert result["patch_applied"] is None

    grader["patch_apply_status"] = "APPLIED"
    borrowed = fresh_sandbox_regrade.build_fresh_result(TASK_ID, task, "d" * 64, grader)
    assert borrowed["candidate_installed"] is False
    assert borrowed["resolved"] is None


# ---------------------------------------------------------------------------
# the report can represent a terminal candidate
# ---------------------------------------------------------------------------

def test_report_counts_a_passing_terminal_calibration_task(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    task_dir, _, state_sha = _terminal_task(run / "tasks" / TASK_ID)
    _fresh_regrade(task_dir, {"task_id": TASK_ID, "track": "terminal-bench"}, state_sha)
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert f"CALIBRATION | terminal-bench | {TASK_ID} | RESOLVED | NO" in report
    assert "CALIBRATION_EXECUTED: 1/1" in report
    assert "CALIBRATION_RESOLVED: 1/1" in report
    assert "CALIBRATION_INVALID: 0" in report


def test_report_rejects_a_terminal_candidate_whose_recorded_state_drifted(tmp_path, monkeypatch):
    """The identity digest must be recomputed from the recorded trial, not trusted."""
    run = _fixture(tmp_path, monkeypatch)
    task_dir, trial, state_sha = _terminal_task(run / "tasks" / TASK_ID)
    _fresh_regrade(task_dir, {"task_id": TASK_ID, "track": "terminal-bench"}, state_sha)
    (trial / "artifacts" / "app" / "src" / "worker.py").write_text("tampered\n")
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert f"CALIBRATION | terminal-bench | {TASK_ID} | INVALID" in report
    assert "CALIBRATION_EXECUTED: 0/1" in report


def test_report_rejects_a_recorded_artifact_type_that_disagrees_with_the_track(tmp_path, monkeypatch):
    """The recorded artifact type is cross-checked against the manifest track."""
    run = _fixture(tmp_path, monkeypatch)
    task_dir, _, state_sha = _terminal_task(run / "tasks" / TASK_ID)
    _fresh_regrade(task_dir, {"task_id": TASK_ID, "track": "terminal-bench"}, state_sha)
    export_path = task_dir / "trial-export-result.json"
    _write_json(export_path, json.loads(export_path.read_text()) | {
        "candidate_artifact_type": "GIT_PATCH"})
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert f"CALIBRATION | terminal-bench | {TASK_ID} | INVALID" in report


def test_report_rejects_a_terminal_candidate_with_the_unproven_process(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    task_dir, _, state_sha = _terminal_task(run / "tasks" / TASK_ID, phase_process=False)
    _fresh_regrade(task_dir, {"task_id": TASK_ID, "track": "terminal-bench"}, state_sha)
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert f"CALIBRATION | terminal-bench | {TASK_ID} | INVALID" in report


def test_report_rejects_a_terminal_record_that_ran_an_agent_phase(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    task_dir, _, state_sha = _terminal_task(run / "tasks" / TASK_ID)
    _fresh_regrade(task_dir, {"task_id": TASK_ID, "track": "terminal-bench"}, state_sha)
    for name in ("grader-result.json", "fresh-sandbox-result.json"):
        path = task_dir / name
        data = json.loads(path.read_text())
        data["replay_agent_phase_executed"] = True
        _write_json(path, data)
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert f"CALIBRATION | terminal-bench | {TASK_ID} | INVALID" in report


# ---------------------------------------------------------------------------
# helpers shared with the terminal adapter fixtures
# ---------------------------------------------------------------------------

_STREAM = b'{"type":"assistant","message":"recorded"}\n'
_TASK_TOML = """
schema_version = "1.2"

artifacts = ["/app/src/"]

[task]
name = "terminal-bench/payments-pipeline-fix"

[verifier]
timeout_sec = 600.0
environment_mode = "separate"

[agent]
timeout_sec = 28800.0
"""


def _layout(tmp_path):
    upstream = tmp_path / "upstream"
    repo = tmp_path / "repo"
    repo.mkdir()
    task_dir = upstream / "terminal-bench" / "tasks" / "payments-pipeline-fix"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(_TASK_TOML)
    (task_dir / "solution").mkdir()
    (task_dir / "tests").mkdir()
    source = tmp_path / "job" / "source-trial"
    (source / "agent").mkdir(parents=True)
    (source / "verifier").mkdir(parents=True)
    (source / "artifacts" / "app" / "src").mkdir(parents=True)
    (source / "agent" / "hermes-stream.jsonl").write_bytes(_STREAM)
    (source / "agent" / "hermes-stderr.log").write_text("")
    (source / "agent" / "hermes-process.json").write_text(json.dumps(
        {"exit_code": 0, "timed_out": False, "duration_ms": 1200,
         "container": "proj-main-1", "argv": ["hermes"], "cwd": "/ws"}))
    (source / "artifacts" / "manifest.json").write_text(json.dumps([
        {"source": "/app/src/", "service": "main",
         "destination": "artifacts/app/src", "type": "directory",
         "status": "ok", "exclude": []}]))
    (source / "artifacts" / "app" / "src" / "worker.py").write_text("state\n")
    (source / "verifier" / "reward.txt").write_text("1")
    (source / "lock.json").write_text('{"resolved": true}')
    (source / "config.json").write_text(json.dumps(
        {"task": {"name": "terminal-bench/payments-pipeline-fix", "path": str(task_dir)},
         "artifacts": ["/app/src/"]}))
    (source / "result.json").write_text(json.dumps(
        {"id": "source-id", "task_name": "terminal-bench/payments-pipeline-fix",
         "trial_name": "source-trial",
         "agent_info": {"name": tr.SUT_AGENT_NAME, "version": tr.SUT_AGENT_VERSION,
                        "model_info": {"name": tr.SUT_MODEL_LABEL}},
         "verifier_result": {"rewards": {"reward": 1}}, "exception_info": None}))
    return upstream, repo, task_dir, source


def _replay_trial(tmp_path, source):
    trial = tmp_path / "replays" / "grade-grader-1"
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    (trial / "artifacts").mkdir(parents=True)
    (trial / "agent" / "hermes-stream.jsonl").write_bytes(_STREAM)
    (trial / "verifier" / "reward.txt").write_text("1")
    (trial / "result.json").write_text(json.dumps(
        {"id": "replay-id", "task_name": "terminal-bench/payments-pipeline-fix",
         "verifier_environment_mode": "separate",
         "agent_info": {"name": tr.SUT_AGENT_NAME, "version": tr.SUT_AGENT_VERSION,
                        "model_info": {"name": tr.SUT_MODEL_LABEL}},
         "verifier_result": {"rewards": {"reward": 1}}, "exception_info": None,
         "config": {"source_trial": {"action": "regrade", "type": "local",
                                     "path": str(source)}}}))
    return trial
