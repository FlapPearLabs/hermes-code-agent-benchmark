#!/usr/bin/env python3
"""Append a classified human intervention outside the agent workspace."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent.parent
TAXONOMY = (
    "OWNER_DECISION", "ENVIRONMENT_FIX", "BENCHMARK_INFRA_FIX",
    "SUT_CONFIG_CHANGE", "CREDENTIAL_PROVISION", "MANUAL_RETRY",
    "AGENT_CORRECTION", "OTHER",
)


def log_intervention(run_id, scope, taxonomy, description, evidence, task_id=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id):
        raise ValueError("invalid run_id")
    if taxonomy not in TAXONOMY:
        raise ValueError("invalid taxonomy")
    if scope not in ("run", "task"):
        raise ValueError("scope must be run or task")
    if not description.strip() or not evidence.strip():
        raise ValueError("description and evidence are required")
    if scope == "run" and task_id is not None:
        raise ValueError("run-level intervention cannot have task_id")
    if scope == "task":
        manifest = json.loads((REPO_DIR / "benchmark-manifest.json").read_text())
        task_ids = {task["task_id"] for task in
                    manifest["scored_tasks"] + manifest["calibration_tasks"]}
        if task_id not in task_ids:
            raise ValueError("task_id is absent from manifest")

    run_dir = REPO_DIR / "runs" / run_id
    path = (run_dir / "human-interventions.jsonl" if scope == "run" else
            run_dir / "tasks" / task_id / "human-interventions.jsonl")
    event = {
        "record_type": "intervention_event", "run_id": run_id,
        "scope": scope, "task_id": task_id, "taxonomy": taxonomy,
        "description": description.strip(), "evidence": evidence.strip(),
        "event_count": 1, "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scope", choices=("run", "task"), required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--taxonomy", choices=TAXONOMY, required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    print(log_intervention(args.run_id, args.scope, args.taxonomy,
                           args.description, args.evidence, args.task_id))
