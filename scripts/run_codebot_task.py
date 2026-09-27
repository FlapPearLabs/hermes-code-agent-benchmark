#!/usr/bin/env python3
"""
run_codebot_task.py - Orchestrator for Hermes Code Bot Benchmark task execution.
Coordinates environment handoff, Code Bot execution, candidate patch export, official grading, and regrading.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

def run_task(task_id, run_id="run_001"):
    print(f"==================================================")
    print(f"RUNNING BENCHMARK TASK: {task_id} (run_id: {run_id})")
    print(f"==================================================")

    # 1. Prepare Workspace
    prep_cmd = f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/prepare_agent_workspace.py --task {task_id} --run-id {run_id}"
    subprocess.run(prep_cmd, shell=True, check=True)

    # 2. Record Task Start Event
    event_cmd = f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/collect_telemetry.py --task {task_id} --run-id {run_id} --event TASK_START"
    subprocess.run(event_cmd, shell=True, check=True)

    # 3. Agent Execution placeholder
    # Records classification and engineering events
    subprocess.run(f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/collect_telemetry.py --task {task_id} --run-id {run_id} --event TASK_CLASSIFIED --details '{{\"class\": \"BUG\"}}'", shell=True, check=True)
    subprocess.run(f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/collect_telemetry.py --task {task_id} --run-id {run_id} --event RISK_CLASSIFIED --details '{{\"risk\": \"RISK_B\"}}'", shell=True, check=True)

    # 4. Export Candidate Patch
    export_cmd = f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/export_candidate_patch.py --task {task_id} --run-id {run_id}"
    subprocess.run(export_cmd, shell=True, check=True)

    # 5. Grade with Official Verifier
    grade_cmd = f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/grade_with_official_verifier.py --task {task_id} --run-id {run_id}"
    subprocess.run(grade_cmd, shell=True, check=True)

    # 6. Fresh Sandbox Regrade
    regrade_cmd = f"{REPO_DIR}/.venv/bin/python {REPO_DIR}/scripts/fresh_sandbox_regrade.py --task {task_id} --run-id {run_id}"
    subprocess.run(regrade_cmd, shell=True, check=True)

    # 7. Finalize telemetry
    summary = {
        "task_id": task_id,
        "run_id": run_id,
        "resolved": False,
        "fresh_sandbox_resolved": False,
        "human_interventions": 0
    }
    sum_cmd = f"{REPO_DIR}/.venv/bin/python -c \"from scripts.collect_telemetry import TaskTelemetryCollector; c = TaskTelemetryCollector('{task_id}', '{run_id}'); c.finalize_summary({summary})\""
    subprocess.run(sum_cmd, shell=True, check=True, cwd=str(REPO_DIR))

    print(f"Task {task_id} execution and verification pipeline completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", default="run_001")
    args = parser.parse_args()
    run_task(args.task, args.run_id)
