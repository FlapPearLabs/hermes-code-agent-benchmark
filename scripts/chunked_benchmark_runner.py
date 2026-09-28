#!/usr/bin/env python3
"""Calibration-only Hermes runner with raw trace capture and fail-closed steps."""

import argparse
import hashlib
import os
import re
import json
import time
import tomllib
import subprocess
import sys
import uuid
from pathlib import Path

if __package__:
    from scripts.collect_telemetry import TaskTelemetryCollector
    from scripts.verify_agent_sandbox import prove_sandbox
    from scripts.verify_protocol_freeze import FreezeError, verify_local_patch_set
    from scripts.grade_with_official_verifier import HARBOR_BIN, HARBOR_ROOT, UPSTREAM
    from scripts.terminal_replay import (SANDBOX_STATE_ARTIFACT,
                                         SANDBOX_STATE_INSTALL_STATUS,
                                         REPLAY_AGENT_STREAM, REPLAY_PROCESS_RECORD,
                                         build_terminal_prompt,
                                         candidate_state_sha256,
                                         candidate_trial_command, locate_trial,
                                         read_candidate_evidence, verify_harbor_pin)
    from scripts.candidate_artifact import check_terminal_artifact_preflight
else:
    from collect_telemetry import TaskTelemetryCollector
    from verify_agent_sandbox import prove_sandbox
    from verify_protocol_freeze import FreezeError, verify_local_patch_set
    from grade_with_official_verifier import HARBOR_BIN, HARBOR_ROOT, UPSTREAM
    from terminal_replay import (SANDBOX_STATE_ARTIFACT, SANDBOX_STATE_INSTALL_STATUS,
                                 REPLAY_AGENT_STREAM, REPLAY_PROCESS_RECORD,
                                 build_terminal_prompt, candidate_state_sha256,
                                 candidate_trial_command, locate_trial,
                                 read_candidate_evidence, verify_harbor_pin)
    from candidate_artifact import check_terminal_artifact_preflight

REPO_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"
STATE_PATH = REPO_DIR / "runs" / "benchmark_run_state.json"
SCRIPTS_DIR = REPO_DIR / "scripts"
PYTHON_BIN = Path(sys.executable)


def verify_sut_unchanged(task_dir):
    protocol = json.loads((REPO_DIR / "PROTOCOL_V2.json").read_text())
    observed = {}
    for name, spec in protocol["external_sha256"].items():
        actual = hashlib.sha256(Path(spec["path"]).read_bytes()).hexdigest()
        observed[name] = {"expected": spec["sha256"], "actual": actual,
                          "matched": actual == spec["sha256"]}
    git_observed = {}
    for name, spec in protocol["external_git"].items():
        runtime = Path(spec["path"])
        head = subprocess.run(["git", "-C", str(runtime), "rev-parse", "HEAD"],
                              capture_output=True, text=True)
        matched = head.returncode == 0 and head.stdout.strip() == spec["sha"]
        if matched and spec.get("local_patch_manifest"):
            try:
                verify_local_patch_set(runtime, REPO_DIR / spec["local_patch_manifest"])
            except (FreezeError, OSError, ValueError):
                matched = False
        elif matched:
            dirty = subprocess.run(["git", "-C", str(runtime), "status", "--porcelain=v1",
                                    "--untracked-files=all"], capture_output=True, text=True)
            matched = dirty.returncode == 0 and not dirty.stdout.strip()
        git_observed[name] = {"expected": spec["sha"], "actual": head.stdout.strip(),
                              "matched": matched}
    status = ("PASS" if all(item["matched"] for item in (*observed.values(), *git_observed.values()))
              else "SUT_IDENTITY_DRIFT")
    (task_dir / "sut-post-agent-check.json").write_text(json.dumps({
        "status": status, "external_sha256": observed, "external_git": git_observed}, indent=2) + "\n")
    if status != "PASS":
        raise RuntimeError("SUT identity changed during agent execution")

def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_state(run_id):
    path = STATE_PATH.parent / run_id / "runner-state.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("run_id") != run_id:
            raise RuntimeError("Existing runner state belongs to another run ID")
        return state
    return {
        "run_id": run_id,
        "status": "CALIBRATION_RUNNING",
        "current_track": "calibration",
        "completed_tasks": {},
        "started_at": time.time(),
        "updated_at": time.time()
    }

def save_state(state):
    path = STATE_PATH.parent / state["run_id"] / "runner-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def _run_terminal_task(task_obj, run_id):
    """Terminal-Bench calibration candidate: a real pinned Harbor source trial
    produced by the pinned host-side Hermes Code profile, followed by the same
    official-grader + fresh-replay evidence chain as the git-patch tracks."""
    task_id = task_obj["task_id"]
    task_dir = REPO_DIR / "runs" / run_id / "tasks" / task_id
    workspace_dir = REPO_DIR / "agent-workspaces" / run_id / task_id
    if task_dir.exists() or workspace_dir.exists():
        raise RuntimeError(f"Task {task_id} already has run artifacts; use a fresh run ID")
    pinned_task_dir = Path(task_obj["task_dir"])
    expected = UPSTREAM / "terminal-bench" / "tasks" / task_id
    if pinned_task_dir.resolve() != expected.resolve() or not pinned_task_dir.is_dir():
        raise RuntimeError(f"Pinned Terminal task is missing for {task_id}")
    harbor_pin = verify_harbor_pin(HARBOR_ROOT, HARBOR_BIN,
                                   path_prefixes=(SCRIPTS_DIR,))

    task_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "PROBLEM.md").write_text(
        build_terminal_prompt(task_obj.get("instruction", "")), encoding="utf-8")
    # The verified sandbox profile expects the workspace shape of a solved task.
    # For Terminal-Bench the graded state lives in the container, so ``repo`` is
    # the SUT's local scratch area rather than a git checkout.
    (workspace_dir / "repo").mkdir(exist_ok=True)
    collector = TaskTelemetryCollector(task_id, run_id)
    task_started = time.monotonic()
    collector.record_event("TASK_START", {"track": "terminal-bench"})

    with (pinned_task_dir / "task.toml").open("rb") as handle:
        task_config = tomllib.load(handle)
    agent_timeout = int(task_config.get("agent", {}).get("timeout_sec", 28800))
    job_name = f"candidate-{uuid.uuid4().hex[:8]}"
    command = candidate_trial_command(
        pinned_task_dir=pinned_task_dir, sut_workspace=workspace_dir,
        sut_task_dir=task_dir, sut_timeout_sec=max(600, agent_timeout - 600),
        job_name=job_name, jobs_dir=task_dir / "trials", harbor_bin=HARBOR_BIN)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(SCRIPTS_DIR), str(HARBOR_ROOT / "src")))
    (task_dir / "harbor-candidate-command.json").write_text(
        json.dumps({"argv": command, "cwd": str(REPO_DIR)}, indent=2) + "\n")
    collector.record_event("CANDIDATE_TRIAL_START", {"job_name": job_name})
    started = time.monotonic()
    try:
        process = subprocess.run(command, cwd=str(REPO_DIR), env=env,
                                 capture_output=True, text=True, timeout=32400)
    except subprocess.TimeoutExpired:
        collector.record_event("CANDIDATE_TRIAL_END", {"timed_out": True})
        raise RuntimeError(f"Candidate trial for {task_id} exceeded the hard wall limit")
    (task_dir / "harbor-candidate.log").write_text(
        (process.stdout or "") + "\n--- stderr ---\n" + (process.stderr or ""),
        encoding="utf-8")
    (task_dir / "harbor-candidate-exit-code.txt").write_text(f"{process.returncode}\n")
    collector.record_event("CANDIDATE_TRIAL_END",
                           {"exit_code": process.returncode,
                            "duration_ms": round((time.monotonic() - started) * 1000)})
    if process.returncode != 0:
        raise RuntimeError(f"Candidate trial failed for {task_id}; see harbor-candidate.log")

    candidate_trial = locate_trial(task_dir / "trials" / job_name, task_id)
    verify_sut_unchanged(task_dir)
    preflight = check_terminal_artifact_preflight(pinned_task_dir, candidate_trial, task_id)
    sut = read_candidate_evidence(candidate_trial, task_id)
    state_sha = candidate_state_sha256(candidate_trial)
    stream_path = candidate_trial / "agent" / REPLAY_AGENT_STREAM
    process_json = candidate_trial / "agent" / REPLAY_PROCESS_RECORD
    sut_record = json.loads(process_json.read_text())
    (task_dir / "trial-export-result.json").write_text(json.dumps({
        "status": "VALID", "task_id": task_id, "run_id": run_id,
        "candidate_artifact_type": "SANDBOX_STATE",
        "candidate_trial_dir": str(candidate_trial),
        "trial_id": preflight["trial_id"],
        "candidate_state_sha256": state_sha,
        "hermes_stream_path": str(stream_path),
        "hermes_stream_sha256": sut["sut_stream_sha256"],
        "declared_artifacts": preflight["declared_artifacts"],
        "source_trial_authenticity": preflight["source_trial_authenticity"],
        "sut": sut,
        "harbor_pin": harbor_pin,
        "preflight": dict(preflight),
    }, indent=2, sort_keys=True) + "\n")

    trace = collector.ingest_stream(
        stream_path, candidate_trial / "agent" / "hermes-stderr.log",
        exit_code=sut_record.get("exit_code"),
        duration_ms=sut_record.get("duration_ms") or 0,
        timed_out=bool(sut_record.get("timed_out")))
    if trace["trace_status"] != "COMPLETE":
        raise RuntimeError(
            f"Hermes trace for terminal task {task_id} is incomplete; see {candidate_trial}")

    for script, start_event, end_event in (
        ("grade_with_official_verifier.py", "GRADER_START", "GRADER_END"),
        ("fresh_sandbox_regrade.py", "FRESH_REGRADE_START", "FRESH_REGRADE_END"),
    ):
        collector.record_event(start_event)
        step_start = time.monotonic()
        subprocess.run([str(PYTHON_BIN), str(SCRIPTS_DIR / script), "--task", task_id,
                        "--run-id", run_id], check=True)
        collector.record_event(end_event, {"duration_ms": round((time.monotonic() - step_start) * 1000)})

    grade_path = task_dir / "grader-result.json"
    regrade_path = task_dir / "fresh-regrade-result.json"
    grade = json.loads(grade_path.read_text(encoding="utf-8"))
    regrade = json.loads(regrade_path.read_text(encoding="utf-8"))
    if grade.get("task_id") != task_id or regrade.get("task_id") != task_id:
        raise RuntimeError(f"Grade artifacts do not match task {task_id}")
    if (grade.get("status") not in ("PASS", "FAIL") or
            regrade.get("status") != grade["status"] or
            grade.get("official_grader_executed") is not True or
            grade.get("candidate_artifact_type") != SANDBOX_STATE_ARTIFACT or
            regrade.get("candidate_artifact_type") != SANDBOX_STATE_ARTIFACT or
            grade.get("patch_apply_status") != SANDBOX_STATE_INSTALL_STATUS or
            regrade.get("patch_apply_status") != SANDBOX_STATE_INSTALL_STATUS or
            regrade.get("candidate_installed") is not True or
            grade.get("replay_agent_phase_executed") is not False or
            regrade.get("resolved") is not grade.get("resolved") or
            regrade.get("candidate_patch_sha256") != grade.get("candidate_patch_sha256") or
            grade.get("candidate_patch_sha256") != state_sha or
            not grade.get("sandbox_identity") or
            not regrade.get("sandbox_identity") or
            grade["sandbox_identity"] == regrade["sandbox_identity"]):
        raise RuntimeError(f"Official grader or fresh sandbox evidence is invalid for {task_id}")
    for result in (grade, regrade):
        raw = result.get("raw_result_path")
        if not raw or not Path(raw).is_file() or not Path(raw).resolve().is_relative_to(task_dir.resolve()):
            raise RuntimeError(f"Raw official result missing for {task_id}")
    result = {"status": "INFRA_VALID", "resolved": grade["resolved"],
              "task_id": task_id, "run_id": run_id, "completed_at": time.time(),
              "total_wall_duration_ms": round((time.monotonic() - task_started) * 1000),
              "grader_report": str(grade_path), "fresh_regrade_report": str(regrade_path)}
    collector.finalize_summary({**trace, **result})
    return result


def run_single_task(task_obj, track_name, run_id):
    if track_name != "calibration":
        raise ValueError("Scored tasks are disabled for this runner")
    task_id = task_obj["task_id"]
    if task_obj.get("track") == "terminal-bench":
        return _run_terminal_task(task_obj, run_id)
    task_dir = REPO_DIR / "runs" / run_id / "tasks" / task_id
    workspace_dir = REPO_DIR / "agent-workspaces" / run_id / task_id
    if task_dir.exists() or workspace_dir.exists():
        raise RuntimeError(f"Task {task_id} already has run artifacts; use a fresh run ID")

    task_started = time.monotonic()
    cmd_prep = [str(PYTHON_BIN), str(SCRIPTS_DIR / "prepare_agent_workspace.py"), "--task", task_id, "--run-id", run_id]
    subprocess.run(cmd_prep, check=True)
    collector = TaskTelemetryCollector(task_id, run_id)
    collector.record_event("TASK_START", {"track": track_name})
    sandbox_prefix = prove_sandbox(workspace_dir, task_dir, REPO_DIR)
    prompt = f"Please solve the problem in {workspace_dir / 'PROBLEM.md'} within repository {workspace_dir / 'repo'}. Inspect files, implement the minimal correct fix, test if possible, and exit cleanly."
    agent_cmd = [
        "hermes", "-p", "code", "chat",
        "-q", prompt,
        "--yolo",
        "--max-turns", "60",
        "--format", "stream-json",
    ]
    run_env = dict(os.environ)
    run_env["HERMES_YOLO_MODE"] = "1"
    # A shell started inside an unrelated Kanban worker must not silently turn
    # this benchmark task into that worker or inherit its Goal loop.
    if any(key.startswith("HERMES_KANBAN_") for key in run_env):
        raise RuntimeError("Inherited Kanban worker environment is not a benchmark run")

    stdout_path = task_dir / "hermes-stream.jsonl"
    stderr_path = task_dir / "hermes-stderr.log"
    exit_code = None
    timed_out = False
    process_error = None
    started = time.monotonic()
    collector.record_event("AGENT_PROCESS_START", {"command": agent_cmd, "sandbox_proof": str(task_dir / "agent-sandbox-proof.json")})
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.run(sandbox_prefix + agent_cmd, cwd=str(workspace_dir / "repo"), timeout=1800,
                                     env=run_env, stdout=stdout, stderr=stderr)
            exit_code = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        process_error = "Hermes exceeded the 1800-second task limit"
    except OSError as exc:
        process_error = f"Hermes process could not start: {exc}"
    duration_ms = round((time.monotonic() - started) * 1000)
    process_record = {"exit_code": exit_code, "duration_ms": duration_ms,
                      "agent_start_monotonic": started, "agent_end_monotonic": time.monotonic(),
                      "timed_out": timed_out, "error": process_error,
                      "stdout": str(stdout_path), "stderr": str(stderr_path)}
    (task_dir / "hermes-process.json").write_text(json.dumps(process_record, indent=2), encoding="utf-8")
    trace = collector.ingest_stream(stdout_path, stderr_path, exit_code=exit_code,
                                    duration_ms=duration_ms, timed_out=timed_out)
    if exit_code != 0 or trace["trace_status"] != "COMPLETE":
        raise RuntimeError(f"Hermes task {task_id} failed or its trace is incomplete; see {task_dir}")
    verify_sut_unchanged(task_dir)

    for script, start_event, end_event in (
        ("export_candidate_patch.py", "GIT_DIFF_EXPORT_START", "GIT_DIFF_EXPORT_END"),
        ("grade_with_official_verifier.py", "GRADER_START", "GRADER_END"),
        ("fresh_sandbox_regrade.py", "FRESH_REGRADE_START", "FRESH_REGRADE_END"),
    ):
        collector.record_event(start_event)
        step_start = time.monotonic()
        subprocess.run([str(PYTHON_BIN), str(SCRIPTS_DIR / script), "--task", task_id,
                        "--run-id", run_id], check=True)
        collector.record_event(end_event, {"duration_ms": round((time.monotonic() - step_start) * 1000)})

    grade_path = task_dir / "grader-result.json"
    regrade_path = task_dir / "fresh-regrade-result.json"
    grade = json.loads(grade_path.read_text(encoding="utf-8"))
    regrade = json.loads(regrade_path.read_text(encoding="utf-8"))
    if grade.get("task_id") != task_id or regrade.get("task_id") != task_id:
        raise RuntimeError(f"Grade artifacts do not match task {task_id}")
    if (grade.get("status") not in ("PASS", "FAIL") or
            regrade.get("status") != grade["status"] or
            grade.get("official_grader_executed") is not True or
            grade.get("patch_apply_status") != "APPLIED" or
            regrade.get("patch_applied") is not True or
            regrade.get("patch_apply_status") != "APPLIED" or
            regrade.get("resolved") is not grade.get("resolved") or
            regrade.get("candidate_patch_sha256") != grade.get("candidate_patch_sha256") or
            not grade.get("sandbox_identity") or
            not regrade.get("sandbox_identity") or
            grade["sandbox_identity"] == regrade["sandbox_identity"]):
        raise RuntimeError(f"Official grader or fresh sandbox evidence is invalid for {task_id}")
    for result in (grade, regrade):
        raw = result.get("raw_result_path")
        if not raw or not Path(raw).is_file() or not Path(raw).resolve().is_relative_to(task_dir.resolve()):
            raise RuntimeError(f"Raw official result missing for {task_id}")
    result = {"status": "INFRA_VALID", "resolved": grade["resolved"],
              "task_id": task_id, "run_id": run_id, "completed_at": time.time(),
              "total_wall_duration_ms": round((time.monotonic() - task_started) * 1000),
              "grader_report": str(grade_path), "fresh_regrade_report": str(regrade_path)}
    collector.finalize_summary({**trace, **result})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", choices=["calibration"], required=True)
    args = parser.parse_args(argv)
    run_id = args.run_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id):
        parser.error("--run-id must contain only letters, digits, underscore, or hyphen")
    subprocess.run([str(PYTHON_BIN), str(SCRIPTS_DIR / "verify_protocol_freeze.py"),
                    "--run-id", run_id], check=True)
    manifest = load_manifest()
    tasks = manifest.get("calibration_tasks", [])
    if not tasks:
        raise RuntimeError("Manifest has no calibration tasks")
    state = load_state(run_id)
    for task in tasks:
        task_id = task["task_id"]
        if task_id in state["completed_tasks"]:
            continue
        try:
            result = run_single_task(task, "calibration", run_id=run_id)
            if result.get("status") != "INFRA_VALID":
                raise RuntimeError(f"Calibration evidence is not valid for {task_id}")
        except Exception:
            state["status"] = "CALIBRATION_FAILED"
            save_state(state)
            raise
        state["completed_tasks"][task_id] = result
        save_state(state)
    state["status"] = "CALIBRATION_INFRA_VALID"
    save_state(state)
    print(f"Calibration infrastructure valid for {run_id}. Scored tasks were not run.")

if __name__ == "__main__":
    main()
