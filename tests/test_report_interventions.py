"""Report accounting must be backed by grader processes and explicit intervention events."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_report
import log_intervention


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def _fixture(tmp_path, monkeypatch):
    scored = [{"task_id": f"scored-{i:02d}", "track": "swe-bench-verified",
               "is_calibration": False} for i in range(20)]
    calibration = [{"task_id": "calibration-01", "track": "swe-bench-verified",
                    "is_calibration": True}]
    _write_json(tmp_path / "benchmark-manifest.json", {
        "scored_tasks": scored, "calibration_tasks": calibration,
    })
    monkeypatch.setattr(build_report, "MANIFEST_PATH", tmp_path / "benchmark-manifest.json")
    monkeypatch.setattr(build_report, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(build_report, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(log_intervention, "REPO_DIR", tmp_path)
    return tmp_path / "runs" / "run_test"


def _grader(task_dir, status="PASS", *, process=True, raw=True):
    task_dir.mkdir(parents=True, exist_ok=True)
    patch = task_dir / "patch.diff"
    patch.write_text("diff --git a/a b/a\n")
    patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
    result_path = task_dir / "official" / "report.json"
    fresh_result_path = task_dir / "official" / "fresh-report.json"
    if raw:
        _write_json(result_path, {"verdict": status})
    _write_json(fresh_result_path, {"verdict": status})
    _write_json(task_dir / "grader-result.json", {
        "status": status, "resolved": status == "PASS",
        "official_grader_process_started": process,
        "official_grader_executed": process,
        "grader_exit_code": 0, "grader_duration_ms": 12, "patch_apply_status": "APPLIED",
        "sandbox_identity": "container-123", "raw_result_path": str(result_path),
        "candidate_patch_sha256": patch_hash,
    })
    _write_json(task_dir / "fresh-sandbox-result.json", {
        "status": status, "resolved": status == "PASS",
        "official_grader_process_started": process,
        "official_grader_executed": process,
        "grader_exit_code": 0, "grader_duration_ms": 13, "patch_apply_status": "APPLIED",
        "sandbox_identity": "container-456", "raw_result_path": str(fresh_result_path),
        "candidate_patch_sha256": patch_hash,
    })
    _write_json(task_dir / "fresh-regrade-result.json", {
        "status": status, "resolved": status == "PASS", "patch_applied": True,
        "grader_exit_code": 0, "patch_apply_status": "APPLIED",
        "sandbox_identity": "container-456", "raw_result_path": str(fresh_result_path),
        "candidate_patch_sha256": patch_hash,
    })
    if process:
        for prefix in ("grader", "fresh-sandbox"):
            _write_json(task_dir / f"{prefix}-command.json", {
                "argv": ["official-grader"], "cwd": str(task_dir),
            })
            _write_json(task_dir / f"{prefix}-env.json", {"PATH": "/bin"})
            (task_dir / f"{prefix}-exit-code.txt").write_text("0\n")
            (task_dir / f"{prefix}-stdout.log").write_text("grader ran\n")
            (task_dir / f"{prefix}-stderr.log").write_text("")


def test_report_separates_calibration_and_only_counts_verified_scored_processes(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    tasks = run / "tasks"
    _grader(tasks / "scored-00", "PASS")
    _grader(tasks / "scored-01", "FAIL")
    _grader(tasks / "scored-02", "PASS", process=False)
    _grader(tasks / "scored-03", "PASS", raw=False)
    _write_json(tasks / "scored-04" / "grader-result.json", {
        "status": "INFRA_FAIL", "official_grader_process_started": True,
    })
    _write_json(tasks / "scored-05" / "task-summary.json", {"completed": True,
                                                            "resolved": True})
    _grader(tasks / "calibration-01", "PASS")
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert "SCORED_TOTAL: 20" in report
    assert "SCORED_EXECUTED: 2/20" in report
    assert "SCORED_RESOLVED: 1/2" in report
    assert "SCORED_INFRA_FAIL: 1" in report
    assert "SCORED_INVALID: 3" in report
    assert "SCORED_NOT_STARTED: 14" in report
    assert "CALIBRATION_EXECUTED: 1/1" in report
    assert "CALIBRATION_RESOLVED: 1/1" in report
    assert "scored-02 | INVALID" in report
    assert "scored-03 | INVALID" in report
    assert "scored-05 | INVALID" in report


def test_contaminated_run_and_unknown_historical_intervention_count(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    _write_json(run / "RUN_VALIDITY.json", {
        "PERFORMANCE_RESULT_VALID": "NO",
        "STATUS": "PROTOCOL_INVALIDATED_FOR_PERFORMANCE",
    })
    _grader(run / "tasks" / "scored-00")
    log = run / "human-interventions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "record_type": "historical_run_level_intervention_summary",
        "taxonomy": ["SUT_CONFIG_CHANGE", "BENCHMARK_INFRA_FIX"],
        "event_count": None,
    }) + "\n")
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert "SCORED_CONTAMINATED: 20" in report
    assert "CALIBRATION_CONTAMINATED: 1" in report
    assert "SCORED_EXECUTED: 0/20" in report
    assert "SCORED_RESOLVED: N/A" in report
    assert "scored-00 | RESOLVED | YES" in report
    assert "Intervention count: UNKNOWN" in report
    assert "PROTOCOL_INVALIDATED_FOR_PERFORMANCE" in report


def test_intervention_logger_writes_scoped_taxonomy_and_report_counts(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    log_intervention.log_intervention("run_test", "run", "BENCHMARK_INFRA_FIX",
                                      "Fix grader process invocation", "change-123")
    log_intervention.log_intervention("run_test", "task", "MANUAL_RETRY",
                                      "Retry after transient failure", "ticket-456",
                                      task_id="scored-00")
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert "Intervention count: 2 documented events" in report
    assert "Documented run-level events: 1; documented task-level events: 1" in report
    assert "BENCHMARK_INFRA_FIX: 1" in report
    assert "MANUAL_RETRY: 1" in report
    for path in (run / "human-interventions.jsonl",
                 run / "tasks" / "scored-00" / "human-interventions.jsonl"):
        event = json.loads(path.read_text())
        assert event["record_type"] == "intervention_event"
        assert event["event_count"] == 1
        assert event["occurred_at"]


def test_intervention_logger_rejects_nonmanifest_task_and_invalid_taxonomy(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="manifest"):
        log_intervention.log_intervention("run_test", "task", "MANUAL_RETRY",
                                          "Retry", "ticket", task_id="other")
    with pytest.raises(ValueError, match="taxonomy"):
        log_intervention.log_intervention("run_test", "run", "UNKNOWN_KIND",
                                          "Fix", "ticket")
    with pytest.raises(ValueError, match="task_id"):
        log_intervention.log_intervention("run_test", "run", "MANUAL_RETRY",
                                          "Retry", "ticket", task_id="scored-00")


def test_report_requires_the_patch_install_label_for_patch_candidates(tmp_path, monkeypatch):
    """The per-artifact-type install vocabulary must not loosen the git-patch track."""
    run = _fixture(tmp_path, monkeypatch)
    task_dir = run / "tasks" / "scored-00"
    _grader(task_dir)
    for name in ("grader-result.json", "fresh-sandbox-result.json"):
        data = json.loads((task_dir / name).read_text())
        data["patch_apply_status"] = "SEEDED"
        _write_json(task_dir / name, data)
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert "SCORED_EXECUTED: 0/20" in report
    assert "SCORED_RESOLVED: N/A" in report
    assert "SCORED_INVALID: 1" in report


def test_report_never_overwrites_historical_final_report(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    run = tmp_path / "runs" / "run_001"
    legacy = tmp_path / "reports" / "FINAL_BENCHMARK_REPORT.md"
    legacy.parent.mkdir()
    legacy.write_text("historical evidence\n")
    _write_json(run / "RUN_VALIDITY.json", {"PERFORMANCE_RESULT_VALID": "NO"})
    build_report.generate_report("run_001")
    assert legacy.read_text() == "historical evidence\n"
    assert (tmp_path / "reports" / "BENCHMARK_REPORT_run_001.md").exists()


def test_report_cli_requires_explicit_run_id():
    script = Path(build_report.__file__)
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "--run-id" in result.stderr


@pytest.mark.parametrize("defect", ["missing_fresh_raw", "missing_fresh_command",
                                     "same_sandbox", "patch_mismatch", "verdict_mismatch"])
def test_scored_result_requires_independent_matching_fresh_regrade(tmp_path, monkeypatch, defect):
    run = _fixture(tmp_path, monkeypatch)
    task_dir = run / "tasks" / "scored-00"
    _grader(task_dir)
    fresh = task_dir / "fresh-regrade-result.json"
    if defect == "missing_fresh_raw":
        (task_dir / "official" / "fresh-report.json").unlink()
    elif defect == "missing_fresh_command":
        (task_dir / "fresh-sandbox-command.json").unlink()
    else:
        data = json.loads(fresh.read_text())
        if defect == "same_sandbox":
            data["sandbox_identity"] = "container-123"
        elif defect == "patch_mismatch":
            data["candidate_patch_sha256"] = "0" * 64
        else:
            data["status"] = "FAIL"
            data["resolved"] = False
        _write_json(fresh, data)
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert "SCORED_EXECUTED: 0/20" in report
    assert "SCORED_RESOLVED: N/A" in report
    assert "SCORED_INVALID: 1" in report


def test_explicit_fresh_infrastructure_failure_is_not_an_invalid_verdict(tmp_path, monkeypatch):
    run = _fixture(tmp_path, monkeypatch)
    task_dir = run / "tasks" / "scored-00"
    _grader(task_dir)
    for name in ("fresh-sandbox-result.json", "fresh-regrade-result.json"):
        path = task_dir / name
        outcome = json.loads(path.read_text())
        outcome.update(status="INFRA_FAIL", resolved=None)
        _write_json(path, outcome)
    build_report.generate_report("run_test")
    report = (tmp_path / "reports" / "BENCHMARK_REPORT_run_test.md").read_text()
    assert "SCORED_EXECUTED: 0/20" in report
    assert "SCORED_INFRA_FAIL: 1" in report
    assert "SCORED_INVALID: 0" in report
