"""Deterministic checks for grader parsing and fresh replay evidence."""

import json
import hashlib
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import grade_with_official_verifier as grader
import fresh_sandbox_regrade as fresh
from grade_with_official_verifier import parse_harbor_result, parse_swe_result
from fresh_sandbox_regrade import build_fresh_result


def write_patch_evidence(task_dir, task_id):
    patch = task_dir / "patch.diff"
    patch.write_text("diff --git a/a b/a\n")
    (task_dir / "workspace-manifest.json").write_text(json.dumps({
        "task_id": task_id, "run_id": "calibration", "base_sha": "base", "base_tree": "tree"}))
    (task_dir / "patch-export-result.json").write_text(json.dumps({
        "status": "VALID", "task_id": task_id, "run_id": "calibration",
        "candidate_artifact_type": "GIT_PATCH",
        "base_sha": "base", "base_tree": "tree",
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest()}))


def test_swe_pass_and_fail_require_official_report_and_apply_log(tmp_path):
    report = tmp_path / "report.json"
    log = tmp_path / "run_instance.log"
    log.write_text("Container for task started: container-123\n>>>>> Applied Patch\n")
    for resolved, expected in ((True, "PASS"), (False, "FAIL")):
        report.write_text(json.dumps({"task": {"resolved": resolved}}))
        result = parse_swe_result("task", report, log, 0)
        assert result["status"] == expected
        assert result["patch_apply_status"] == "APPLIED"
        assert result["sandbox_identity"] == "container-123"


def test_process_crash_is_infrastructure_failure(tmp_path):
    result = parse_swe_result(
        "task", tmp_path / "missing.json", tmp_path / "missing.log", 17
    )
    assert result["status"] == "INFRA_FAIL"
    assert result["resolved"] is None


def test_harbor_apply_failure_cannot_become_a_pass(tmp_path):
    trial = tmp_path / "instance_task"
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir()
    (trial / "result.json").write_text(json.dumps({
        "task_name": "swebench-pro/task",
        "id": "trial-123",
        "exception_info": None,
        "verifier_result": {"rewards": {"reward": 1}},
    }))
    (trial / "agent" / "replay.json").write_text(json.dumps({
        "task": "task", "patch": "/source/agent/model.patch", "apply_rc": 1,
    }))
    (trial / "verifier" / "reward.txt").write_text("1\n")
    result = parse_harbor_result(
        "task", tmp_path, 0, Path("/source/agent/model.patch")
    )
    assert result["status"] == "INVALID"
    assert result["patch_apply_status"] == "PATCH_APPLY_FAIL"
    fresh = build_fresh_result("task", {"base_commit": "abc"}, "0" * 64, result)
    assert fresh["patch_applied"] is False
    assert fresh["resolved"] is None


@pytest.mark.parametrize("resolved,expected", [(True, "PASS"), (False, "FAIL")])
def test_fake_official_process_drives_status(tmp_path, monkeypatch, resolved, expected):
    task_id = "example__repo-1"
    task = {"task_id": task_id, "track": "swe-bench-verified",
            "base_commit": "base", "upstream_sha": grader.PINS["swe-bench-verified"][1]}
    (tmp_path / "benchmark-manifest.json").write_text(json.dumps({
        "calibration_tasks": [task], "scored_tasks": []
    }))
    task_dir = tmp_path / "runs" / "calibration" / "tasks" / task_id
    task_dir.mkdir(parents=True)
    write_patch_evidence(task_dir, task_id)
    dataset = tmp_path / "pinned.parquet"
    dataset.write_bytes(b"pinned")
    monkeypatch.setattr(grader, "REPO_DIR", tmp_path)
    monkeypatch.setattr(grader, "VERIFIED_PARQUET", dataset)
    monkeypatch.setattr(grader, "_verify_pin", lambda *_: None)

    def fake_process(command, cwd, env, evidence_dir, phase):
        run_id = command[command.index("--run_id") + 1]
        raw = cwd / "logs/evaluation" / run_id / "hermes-code-bot" / task_id
        raw.mkdir(parents=True)
        (raw / "report.json").write_text(json.dumps({task_id: {"resolved": resolved}}))
        (raw / "run_instance.log").write_text(
            f"Container for {task_id} started: container-456\n>>>>> Applied Patch\n"
        )
        return 0, True, 17

    monkeypatch.setattr(grader, "_invoke", fake_process)
    result = grader.grade_task(task_id, "calibration")
    assert result["status"] == expected
    assert result["official_grader_executed"] is True
    assert result["sandbox_identity"] == "container-456"


def test_fake_official_process_crash_is_not_a_grader_fail(tmp_path, monkeypatch):
    task_id = "example__repo-1"
    (tmp_path / "benchmark-manifest.json").write_text(json.dumps({
        "calibration_tasks": [{"task_id": task_id, "track": "swe-bench-verified",
                               "upstream_sha": grader.PINS["swe-bench-verified"][1]}],
        "scored_tasks": []
    }))
    task_dir = tmp_path / "runs" / "calibration" / "tasks" / task_id
    task_dir.mkdir(parents=True)
    write_patch_evidence(task_dir, task_id)
    dataset = tmp_path / "pinned.parquet"
    dataset.write_bytes(b"pinned")
    monkeypatch.setattr(grader, "REPO_DIR", tmp_path)
    monkeypatch.setattr(grader, "VERIFIED_PARQUET", dataset)
    monkeypatch.setattr(grader, "_verify_pin", lambda *_: None)
    monkeypatch.setattr(grader, "_invoke", lambda *_: (17, True, 11))
    result = grader.grade_task(task_id, "calibration")
    assert result["status"] == "INFRA_FAIL"
    assert result["official_grader_process_started"] is True
    assert result["official_grader_executed"] is False


def test_historical_grader_run_cannot_be_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(grader, "REPO_DIR", tmp_path)
    with pytest.raises(ValueError, match="historical"):
        grader.grade_task("task", "run_001")
    assert not (tmp_path / "runs" / "run_001").exists()


def test_tampered_patch_is_rejected_before_grader_process(tmp_path, monkeypatch):
    task_id = "example__repo-1"
    task = {"task_id": task_id, "track": "swe-bench-verified",
            "upstream_sha": grader.PINS["swe-bench-verified"][1]}
    (tmp_path / "benchmark-manifest.json").write_text(json.dumps({
        "calibration_tasks": [task], "scored_tasks": []}))
    task_dir = tmp_path / "runs" / "calibration" / "tasks" / task_id
    task_dir.mkdir(parents=True)
    write_patch_evidence(task_dir, task_id)
    (task_dir / "patch.diff").write_text("tampered\n")
    monkeypatch.setattr(grader, "REPO_DIR", tmp_path)
    monkeypatch.setattr(grader, "_verify_pin", lambda *_: None)
    monkeypatch.setattr(grader, "_invoke", lambda *_: pytest.fail("grader must not start"))
    result = grader.grade_task(task_id, "calibration")
    assert result["status"] == "INVALID"
    assert result["official_grader_process_started"] is False


def test_fresh_regrade_requires_distinct_sandbox(tmp_path, monkeypatch):
    task_dir = tmp_path / "runs" / "calibration" / "tasks" / "task"
    task_dir.mkdir(parents=True)
    (task_dir / "grader-result.json").write_text(json.dumps({
        "status": "PASS", "official_grader_executed": True,
        "sandbox_identity": "container-1", "candidate_patch_sha256": "a" * 64}))
    monkeypatch.setattr(fresh, "REPO_DIR", tmp_path)
    monkeypatch.setattr(fresh, "_task", lambda *_: {"base_commit": "base"})
    monkeypatch.setattr(fresh, "grade_task", lambda *_ , **__: {
        "status": "PASS", "official_grader_executed": True,
        "sandbox_identity": "container-1", "candidate_patch_sha256": "a" * 64,
        "patch_apply_status": "APPLIED", "grader_exit_code": 0, "resolved": True})
    result = fresh.fresh_regrade("task", "calibration")
    assert result["status"] == "INVALID"
    assert result["resolved"] is None


def _pro_task_evidence(tmp_path, monkeypatch, task_id="pro-1"):
    """A pro-track task whose only remaining gate is the Harbor provenance."""
    task = {"task_id": task_id, "track": "swe-bench-pro-v2",
            "upstream_sha": "pro-sha", "task_dir": str(tmp_path / "official")}
    (tmp_path / "benchmark-manifest.json").write_text(json.dumps({
        "calibration_tasks": [task], "scored_tasks": []}))
    task_dir = tmp_path / "runs" / "calibration" / "tasks" / task_id
    task_dir.mkdir(parents=True)
    write_patch_evidence(task_dir, task_id)
    monkeypatch.setattr(grader, "REPO_DIR", tmp_path)
    monkeypatch.setattr(grader, "PINS", {"swe-bench-pro-v2": (tmp_path / "pro", "pro-sha")})
    monkeypatch.setattr(grader, "_verify_pin", lambda *_: None)
    return task_dir


def test_pro_track_binds_the_harbor_that_actually_executes(tmp_path, monkeypatch):
    """A matching checkout is not enough: the imported build must be the pinned one."""
    _pro_task_evidence(tmp_path, monkeypatch)
    calls = []

    def boom(root, binary, path_prefixes=()):
        calls.append((root, binary, tuple(path_prefixes)))
        raise RuntimeError("HARBOR_RUNTIME_RESOLUTION_MISMATCH: a != b")

    monkeypatch.setattr(grader.terminal_replay, "verify_harbor_pin", boom)
    monkeypatch.setattr(grader, "_invoke", lambda *_: pytest.fail("grader must not start"))
    result = grader.grade_task("pro-1", "calibration")
    # The probe must replay the leading PYTHONPATH entry the run itself uses.
    assert calls == [(grader.HARBOR_ROOT, grader.HARBOR_BIN,
                      (grader.PRO_ROOT / "v2/tooling",))]
    assert result["status"] == "INVALID"
    assert "HARBOR_RUNTIME_RESOLUTION_MISMATCH" in result["error"]
    assert result["official_grader_process_started"] is False
    assert result["official_grader_executed"] is False


def test_pro_track_provenance_is_checked_before_the_grader_runs(tmp_path, monkeypatch):
    """The pinned provenance must be established, and its result carried into the record."""
    _pro_task_evidence(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr(grader.terminal_replay, "verify_harbor_pin",
                        lambda root, binary, path_prefixes=(): seen.update(
                            root=str(root), runtime_path="/pinned/harbor")
                        or {"pin_sha": "3c82380859d187957cfd5cd64802b076d9779550",
                            "version": "0.23.0", "runtime_path": "/pinned/harbor"})
    monkeypatch.setattr(grader, "_invoke", lambda *_: pytest.fail("grader must not start"))
    result = grader.grade_task("pro-1", "calibration")
    assert seen["root"] == str(grader.HARBOR_ROOT)
    assert result["status"] == "INVALID"
    assert "Pro V2 task directory is not the pinned upstream task" in result["error"]
