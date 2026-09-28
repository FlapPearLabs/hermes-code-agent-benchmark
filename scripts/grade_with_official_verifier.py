#!/usr/bin/env python3
"""Invoke pinned official evaluators and retain their raw evidence."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone


REPO_DIR = Path(__file__).resolve().parent.parent
UPSTREAM = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check")
SWE_ROOT = UPSTREAM / "swe-bench"
PRO_ROOT = UPSTREAM / "swe-bench-pro"
HARBOR_ROOT = UPSTREAM / "harbor"
HARBOR_BIN = Path("/Users/songshiyao/.local/bin/harbor")
PINS = {
    "swe-bench-verified": (SWE_ROOT, "02e7a74ffd0b707aab73d203fe87bdc7c76afc8e"),
    "swe-bench-pro-v2": (PRO_ROOT, "66f92766bba642462d4bbe5479e83f91f9211862"),
}
VERIFIED_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
VERIFIED_PARQUET = (Path.home() / ".cache/huggingface/hub"
                    / "datasets--princeton-nlp--SWE-bench_Verified/snapshots"
                    / VERIFIED_REVISION / "data/test-00000-of-00001.parquet")


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task(task_id):
    manifest = json.loads((REPO_DIR / "benchmark-manifest.json").read_text())
    matches = [t for t in manifest["calibration_tasks"] + manifest["scored_tasks"]
               if t["task_id"] == task_id]
    if len(matches) != 1:
        raise ValueError(f"task id absent or duplicated in manifest: {task_id}")
    return matches[0]


def _verify_pin(root, sha):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0 or result.stdout.strip() != sha:
        raise ValueError(f"pinned upstream mismatch: {root}")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
    )
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError(f"pinned upstream working tree is not clean: {root}")


def _check_inputs(task, task_dir):
    export = json.loads((task_dir / "patch-export-result.json").read_text())
    workspace = json.loads((task_dir / "workspace-manifest.json").read_text())
    if export.get("status") != "VALID":
        raise ValueError("patch export is not VALID")
    if (workspace.get("task_id") != task["task_id"] or
            export.get("run_id") != workspace.get("run_id") or
            export.get("base_sha") != workspace.get("base_sha") or
            export.get("base_tree") != workspace.get("base_tree")):
        raise ValueError("patch export differs from pristine workspace identity")
    patch = task_dir / "patch.diff"
    if not patch.is_file() or patch.stat().st_size == 0:
        raise ValueError("candidate patch is missing or empty")
    if export.get("patch_sha256") != _sha256(patch):
        raise ValueError("candidate patch differs from mechanical export")
    if export.get("task_id") != task["task_id"]:
        raise ValueError("candidate patch belongs to another task")
    track = task["track"]
    if track not in PINS:
        raise ValueError(f"UNSUPPORTED_STATE: no proven patch replay for {track}")
    root, sha = PINS[track]
    _verify_pin(root, sha)
    if task.get("upstream_sha") != sha:
        raise ValueError("task manifest upstream SHA differs from pinned evaluator")
    if track == "swe-bench-pro-v2":
        _verify_pin(HARBOR_ROOT, "3c82380859d187957cfd5cd64802b076d9779550")
        version = subprocess.run([str(HARBOR_BIN), "--version"], capture_output=True, text=True)
        if version.returncode != 0 or version.stdout.strip() != "0.23.0":
            raise ValueError("Harbor 0.23.0 is unavailable")
    elif not VERIFIED_PARQUET.is_file():
        raise ValueError("pinned SWE-bench Verified dataset snapshot is unavailable")
    return patch


def parse_swe_result(task_id, report_path, log_path, exit_code):
    """Treat an absent report or absent fresh-container evidence as infrastructure failure."""
    result = {"status": "INFRA_FAIL", "resolved": None,
              "patch_apply_status": "UNKNOWN", "sandbox_identity": None,
              "sandbox_identity_kind": "docker_container_id",
              "raw_result_path": str(report_path)}
    if not log_path.is_file():
        return result
    log = log_path.read_text(errors="replace")
    container = re.search(r"Container for .+ started: (\S+)", log)
    result["sandbox_identity"] = container.group(1) if container else None
    if ">>>>> Patch Apply Failed" in log:
        result.update(status="INVALID", patch_apply_status="PATCH_APPLY_FAIL")
        return result
    if exit_code != 0 or not report_path.is_file() or not container:
        return result
    if ">>>>> Applied Patch" not in log:
        return result
    result["patch_apply_status"] = "APPLIED"
    try:
        resolved = json.loads(report_path.read_text())[task_id]["resolved"]
    except (ValueError, KeyError, TypeError):
        return result
    if type(resolved) is not bool:
        return result
    result.update(status="PASS" if resolved else "FAIL", resolved=resolved)
    return result


def parse_harbor_result(task_id, job_dir, exit_code, source_patch):
    """Require official reward, replay record, and a successful patch application."""
    result = {"status": "INFRA_FAIL", "resolved": None,
              "patch_apply_status": "UNKNOWN", "sandbox_identity": None,
              "sandbox_identity_kind": "harbor_trial_id",
              "raw_result_path": None}
    trials = [p for p in job_dir.glob("instance_*/result.json") if p.is_file()]
    if len(trials) != 1:
        return result
    trial = trials[0].parent
    result["raw_result_path"] = str(trials[0])
    try:
        raw = json.loads(trials[0].read_text())
        replay = json.loads((trial / "agent" / "replay.json").read_text())
    except (OSError, ValueError):
        return result
    result["sandbox_identity"] = raw.get("id")
    if raw.get("task_name", "").split("/")[-1] != task_id:
        return result
    if replay.get("task") != task_id or replay.get("patch") != str(source_patch):
        return result
    if replay.get("apply_rc") != 0:
        result.update(status="INVALID", patch_apply_status="PATCH_APPLY_FAIL")
        return result
    result["patch_apply_status"] = "APPLIED"
    if exit_code != 0 or raw.get("exception_info") is not None or not result["sandbox_identity"]:
        return result
    reward_file = trial / "verifier" / "reward.txt"
    try:
        reward_text = reward_file.read_text().strip()
        reward = raw["verifier_result"]["rewards"]["reward"]
    except (OSError, KeyError, TypeError):
        return result
    if reward_text not in ("0", "1") or type(reward) not in (int, float):
        return result
    if reward != int(reward_text) or reward not in (0, 1):
        return result
    resolved = bool(reward)
    result.update(status="PASS" if resolved else "FAIL", resolved=resolved)
    return result


def _invoke(command, cwd, env, evidence_dir, prefix):
    _json(evidence_dir / f"{prefix}-command.json", {"argv": command, "cwd": str(cwd)})
    _json(evidence_dir / f"{prefix}-env.json", {
        "PATH": env.get("PATH"), "PYTHONPATH": env.get("PYTHONPATH"),
        "DOCKER_HOST": env.get("DOCKER_HOST"),
        "HF_DATASETS_OFFLINE": env.get("HF_DATASETS_OFFLINE"),
        "HF_HUB_OFFLINE": env.get("HF_HUB_OFFLINE"),
    })
    started_at = time.monotonic()
    try:
        process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        code, stdout, stderr = process.returncode, process.stdout, process.stderr
        started = True
    except OSError as exc:
        code, stdout, stderr = -1, "", f"{type(exc).__name__}: {exc}\n"
        started = False
    (evidence_dir / f"{prefix}-stdout.log").write_text(stdout)
    (evidence_dir / f"{prefix}-stderr.log").write_text(stderr)
    (evidence_dir / f"{prefix}-exit-code.txt").write_text(f"{code}\n")
    duration_ms = max(1, round((time.monotonic() - started_at) * 1000))
    return code, started, duration_ms


def grade_task(task_id, run_id, phase="grader"):
    if phase not in ("grader", "fresh-sandbox"):
        raise ValueError(f"unknown grading phase: {phase}")
    if run_id == "run_001" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id):
        raise ValueError("historical or unsafe run ID")
    task_dir = REPO_DIR / "runs" / run_id / "tasks" / task_id
    outcome_path = task_dir / ("grader-result.json" if phase == "grader" else "fresh-sandbox-result.json")
    if outcome_path.exists():
        raise ValueError("existing official grader evidence is immutable")
    task_dir.mkdir(parents=True, exist_ok=True)
    outcome = {"task_id": task_id, "run_id": run_id, "status": "INVALID",
               "resolved": None, "official_grader_process_started": False,
               "official_grader_executed": False,
               "patch_apply_status": "UNKNOWN", "grader_exit_code": None,
               "sandbox_identity": None, "raw_result_path": None,
               "timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        task = _task(task_id)
        patch = _check_inputs(task, task_dir)
        outcome.update(track=task["track"], candidate_patch_sha256=_sha256(patch),
                       base_identity=task.get("base_commit") or task.get("container_image")
                       or task.get("upstream_sha"))
        nonce = uuid4().hex
        if task["track"] == "swe-bench-verified":
            eval_id = f"{run_id}-{phase}-{task_id}-{nonce}"
            model = "hermes-code-bot"
            prediction = task_dir / f"{phase}-prediction.jsonl"
            prediction.write_text(json.dumps({
                "instance_id": task_id, "model_name_or_path": model,
                "model_patch": patch.read_text(),
            }) + "\n")
            command = [str(SWE_ROOT / ".venv/bin/python"), "-m", "swebench.harness.run_evaluation",
                       "--dataset_name", str(VERIFIED_PARQUET), "--split", "test",
                       "--predictions_path", str(prediction), "--instance_ids", task_id,
                       "--max_workers", "1", "--run_id", eval_id]
            cwd, env = task_dir, dict(os.environ)
            env["PYTHONPATH"] = str(SWE_ROOT)
            env["HF_DATASETS_OFFLINE"] = "1"
            env["HF_HUB_OFFLINE"] = "1"
            outcome.update(dataset_revision=VERIFIED_REVISION,
                           dataset_file_sha256=_sha256(VERIFIED_PARQUET))
            log_dir = cwd / "logs/evaluation" / eval_id / model / task_id
            code, started, duration_ms = _invoke(command, cwd, env, task_dir, phase)
            outcome["official_grader_process_started"] = started
            outcome["grader_exit_code"] = code
            outcome["grader_duration_ms"] = duration_ms
            outcome.update(parse_swe_result(task_id, log_dir / "report.json",
                                            log_dir / "run_instance.log", code))
            outcome["raw_summary_path"] = str(cwd / "logs/evaluation" / eval_id / "results.json")
        else:
            official_task = PRO_ROOT / "v2/tasks" / task_id
            if official_task.resolve() != Path(task["task_dir"]).resolve() or not official_task.is_dir():
                raise ValueError("Pro V2 task directory is not the pinned upstream task")
            with (official_task / "task.toml").open("rb") as f:
                task_config = tomllib.load(f)
            source = task_dir / f"{phase}-source-job" / "instance_0"
            (source / "agent").mkdir(parents=True, exist_ok=True)
            _json(source / "result.json", {"task_name": task_config["task"]["name"]})
            source_patch = source / "agent/model.patch"
            shutil.copyfile(patch, source_patch)
            if _sha256(source_patch) != outcome["candidate_patch_sha256"]:
                raise ValueError("staged replay patch differs from candidate")
            jobs_dir = task_dir / "official-jobs"
            job_name = f"{phase}-{nonce}"
            command = [str(HARBOR_BIN), "run", "-p", str(official_task), "-e", "docker",
                       "-a", "patch_replay:PatchReplayAgent", "-m", "replay",
                       "--ak", f"source_job={source.parent}", "--job-name", job_name,
                       "--jobs-dir", str(jobs_dir)]
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join((str(PRO_ROOT / "v2/tooling"),
                                                  str(HARBOR_ROOT / "src")))
            outcome.update(base_identity=task_config["environment"].get("docker_image"),
                           staged_patch_sha256=_sha256(source_patch))
            code, started, duration_ms = _invoke(command, task_dir, env, task_dir, phase)
            outcome["official_grader_process_started"] = started
            outcome["grader_exit_code"] = code
            outcome["grader_duration_ms"] = duration_ms
            outcome.update(parse_harbor_result(task_id, jobs_dir / job_name, code, source_patch))
    except (OSError, ValueError, KeyError) as exc:
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    outcome["official_grader_executed"] = outcome["status"] in ("PASS", "FAIL")
    _json(outcome_path, outcome)
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = grade_task(args.task, args.run_id)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] in ("PASS", "FAIL") else 1)
