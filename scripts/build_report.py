#!/usr/bin/env python3
"""Report manifest-scoped benchmark outcomes only when official evidence exists."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

if __package__:
    from scripts.log_intervention import TAXONOMY
else:
    from log_intervention import TAXONOMY


REPO_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"
RUNS_ROOT = REPO_DIR / "runs"
REPORTS_DIR = REPO_DIR / "reports"
SCORED_TOTAL = 20


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _valid_process(task_dir, grader, prefix):
    if not isinstance(grader, dict):
        return False
    status = grader.get("status")
    if status not in ("PASS", "FAIL") or grader.get("resolved") is not (status == "PASS"):
        return False
    if grader.get("official_grader_process_started") is not True or grader.get("official_grader_executed") is not True:
        return False
    if grader.get("grader_exit_code") != 0 or grader.get("patch_apply_status") != "APPLIED":
        return False
    if not grader.get("sandbox_identity"):
        return False
    command = _read_json(task_dir / f"{prefix}-command.json")
    if not isinstance(command, dict) or not isinstance(command.get("argv"), list) or not command["argv"]:
        return False
    if not isinstance(_read_json(task_dir / f"{prefix}-env.json"), dict):
        return False
    if not isinstance(grader.get("grader_duration_ms"), (int, float)) or grader["grader_duration_ms"] <= 0:
        return False
    try:
        if int((task_dir / f"{prefix}-exit-code.txt").read_text().strip()) != 0:
            return False
        raw_path = Path(grader["raw_result_path"]).resolve()
        if not raw_path.is_relative_to(task_dir.resolve()) or not raw_path.is_file():
            return False
        if not (task_dir / f"{prefix}-stdout.log").is_file() or not (task_dir / f"{prefix}-stderr.log").is_file():
            return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def _valid_regrade(task_dir, grader):
    fresh = _read_json(task_dir / "fresh-sandbox-result.json")
    regrade = _read_json(task_dir / "fresh-regrade-result.json")
    if not _valid_process(task_dir, fresh, "fresh-sandbox") or not isinstance(regrade, dict):
        return False
    try:
        patch_hash = hashlib.sha256((task_dir / "patch.diff").read_bytes()).hexdigest()
    except OSError:
        return False
    if not all(result.get("candidate_patch_sha256") == patch_hash
               for result in (grader, fresh, regrade)):
        return False
    if (fresh["sandbox_identity"] == grader["sandbox_identity"] or
            fresh["raw_result_path"] == grader["raw_result_path"]):
        return False
    return (regrade.get("status") == fresh["status"] == grader["status"] and
            regrade.get("resolved") is fresh["resolved"] is grader["resolved"] and
            regrade.get("patch_applied") is True and
            regrade.get("patch_apply_status") == "APPLIED" and
            regrade.get("grader_exit_code") == 0 and
            regrade.get("sandbox_identity") == fresh["sandbox_identity"] and
            regrade.get("raw_result_path") == fresh["raw_result_path"])


def _task_state(task_dir, run_contaminated):
    grader_path = task_dir / "grader-result.json"
    grader = _read_json(grader_path)
    summary = _read_json(task_dir / "task-summary.json")
    contaminated = (run_contaminated or
                    isinstance(grader, dict) and (grader.get("contaminated") is True or grader.get("status") == "CONTAMINATED") or
                    isinstance(summary, dict) and summary.get("contaminated") is True)
    if grader_path.exists():
        if isinstance(grader, dict) and grader.get("status") == "INFRA_FAIL":
            return "INFRA_FAIL", contaminated
        if not _valid_process(task_dir, grader, "grader"):
            return "INVALID", contaminated
        fresh = _read_json(task_dir / "fresh-sandbox-result.json")
        regrade = _read_json(task_dir / "fresh-regrade-result.json")
        if (isinstance(fresh, dict) and fresh.get("status") == "INFRA_FAIL" and
                isinstance(regrade, dict) and regrade.get("status") == "INFRA_FAIL"):
            return "INFRA_FAIL", contaminated
        if _valid_regrade(task_dir, grader):
            return ("RESOLVED" if grader["status"] == "PASS" else "EXECUTED"), contaminated
        return "INVALID", contaminated
    if task_dir.is_dir() and any(p.name != "human-interventions.jsonl" for p in task_dir.iterdir()):
        return "INVALID", contaminated
    return "NOT_STARTED", contaminated


def _intervention_counts(run_dir, tasks):
    counts = Counter()
    taxonomy = Counter()
    unknown = False
    paths = [("run", run_dir / "human-interventions.jsonl")]
    paths += [("task", run_dir / "tasks" / task["task_id"] / "human-interventions.jsonl")
              for task in tasks]
    task_ids = {task["task_id"] for task in tasks}
    for scope, path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                unknown = True
                continue
            if (not isinstance(event, dict) or event.get("record_type") != "intervention_event" or
                    event.get("event_count") != 1 or event.get("scope") != scope or
                    event.get("run_id") != run_dir.name or event.get("taxonomy") not in TAXONOMY or
                    (scope == "run" and event.get("task_id") is not None) or
                    (scope == "task" and
                     (event.get("task_id") not in task_ids or event.get("task_id") != path.parent.name))):
                unknown = True
                continue
            counts[scope] += 1
            taxonomy[event["taxonomy"]] += 1
    return counts, taxonomy, unknown or not (counts["run"] + counts["task"])


def generate_report(run_id, interim_count=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id):
        raise ValueError("invalid run_id")
    manifest = _read_json(MANIFEST_PATH)
    if not isinstance(manifest, dict):
        raise ValueError("benchmark manifest is missing or invalid")
    scored = manifest.get("scored_tasks")
    calibration = manifest.get("calibration_tasks")
    if not isinstance(scored, list) or not isinstance(calibration, list) or len(scored) != SCORED_TOTAL:
        raise ValueError("manifest must contain exactly 20 scored tasks and a calibration list")
    all_tasks = scored + calibration
    ids = [task["task_id"] for task in all_tasks]
    if (len(ids) != len(set(ids)) or
            any(task.get("is_calibration") is True for task in scored) or
            any(task.get("is_calibration") is not True for task in calibration)):
        raise ValueError("manifest scored and calibration tasks overlap or are misclassified")

    run_dir = RUNS_ROOT / run_id
    validity = _read_json(run_dir / "RUN_VALIDITY.json")
    run_status = validity.get("STATUS", "UNSPECIFIED") if isinstance(validity, dict) else "NOT_RECORDED"
    run_contaminated = (isinstance(validity, dict) and
                        (validity.get("PERFORMANCE_RESULT_VALID") == "NO" or
                         run_status == "PROTOCOL_INVALIDATED_FOR_PERFORMANCE"))
    counts = {}
    states = {}
    for label, tasks in (("SCORED", scored), ("CALIBRATION", calibration)):
        states[label] = [(task, *_task_state(run_dir / "tasks" / task["task_id"], run_contaminated))
                         for task in tasks]
        counts[label] = Counter(state for _, state, _ in states[label])

    lines = [f"# Benchmark Report: {run_id}", "", f"RUN_VALIDITY: {run_status}",
             "RESOLVED is a subset of EXECUTED. CONTAMINATED is an independent flag; contaminated tasks are excluded from valid performance counts.", ""]
    for label, tasks in (("SCORED", scored), ("CALIBRATION", calibration)):
        data = counts[label]
        valid_states = [state for _, state, contaminated in states[label] if not contaminated]
        executed = sum(state in ("EXECUTED", "RESOLVED") for state in valid_states)
        resolved = valid_states.count("RESOLVED")
        contaminated_count = sum(contaminated for _, _, contaminated in states[label])
        lines.extend([
            f"## {label}",
            f"{label}_TOTAL: {SCORED_TOTAL if label == 'SCORED' else len(tasks)}",
            f"{label}_EXECUTED: {executed}/{len(tasks)}",
            f"{label}_RESOLVED: {resolved}/{executed}" if executed else f"{label}_RESOLVED: N/A (no valid grader process evidence)",
            f"{label}_INFRA_FAIL: {data['INFRA_FAIL']}",
            f"{label}_INVALID: {data['INVALID']}",
            f"{label}_CONTAMINATED: {contaminated_count}",
            f"{label}_NOT_STARTED: {data['NOT_STARTED']}",
            "",
        ])

    lines.extend(["## Scored Track Results", "Track | Resolved / Executed | Scored slots",
                  "--- | --- | ---"])
    for track in sorted({task["track"] for task in scored}):
        track_states = [state for task, state, contaminated in states["SCORED"]
                        if task["track"] == track and not contaminated]
        executed = sum(state in ("EXECUTED", "RESOLVED") for state in track_states)
        resolved = track_states.count("RESOLVED")
        slots = sum(task["track"] == track for task in scored)
        lines.append(f"{track} | {resolved}/{executed} | {slots}")

    intervention_counts, taxonomy_counts, unknown = _intervention_counts(run_dir, all_tasks)
    documented = intervention_counts["run"] + intervention_counts["task"]
    lines.extend(["", "## Human Interventions"])
    if unknown:
        lines.append(f"Intervention count: UNKNOWN ({documented} individually documented events; historical or missing logs do not establish a total)")
    else:
        lines.append(f"Intervention count: {documented} documented events (completeness not independently proven)")
    lines.append(f"Documented run-level events: {intervention_counts['run']}; documented task-level events: {intervention_counts['task']}")
    for kind, count in sorted(taxonomy_counts.items()):
        lines.append(f"{kind}: {count}")

    lines.extend(["", "## Task States", "Category | Track | Task | State | Contaminated", "--- | --- | --- | --- | ---"])
    for label in ("CALIBRATION", "SCORED"):
        for task, state, contaminated in states[label]:
            lines.append(f"{label} | {task['track']} | {task['task_id']} | {state} | {'YES' if contaminated else 'NO'}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = (f"INTERIM_REPORT_{run_id}_{interim_count:02d}.md" if interim_count is not None else
                f"BENCHMARK_REPORT_{run_id}.md")
    report_path = REPORTS_DIR / filename
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {report_path}")
    return report_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--interim", type=int, help="Interim milestone (5, 10, 15, 20)")
    args = parser.parse_args()
    generate_report(args.run_id, args.interim)
