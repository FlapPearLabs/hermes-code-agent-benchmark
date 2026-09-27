#!/usr/bin/env python3
"""
prepare_agent_workspace.py - Prepare an isolated workspace at base_commit for Hermes Code Bot.
Strictly isolates control plane and private oracles from the agent workspace.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"
WORKSPACES_ROOT = REPO_DIR / "agent-workspaces"

def prepare_workspace(task_id, run_id="run_001"):
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    all_tasks = manifest["calibration_tasks"] + manifest["scored_tasks"]
    task = next((t for t in all_tasks if t["task_id"] == task_id), None)
    if not task:
        raise ValueError(f"Task {task_id} not found in manifest!")

    target_dir = WORKSPACES_ROOT / run_id / task_id
    target_dir.mkdir(parents=True, exist_ok=True)

    track = task["track"]
    instruction = task.get("problem_statement") or task.get("instruction") or ""

    # Write task instruction
    (target_dir / "PROBLEM.md").write_text(instruction)

    # Write task metadata (non-leaking)
    meta = {
        "task_id": task_id,
        "track": track,
        "run_id": run_id,
        "base_commit": task.get("base_commit"),
        "repo": task.get("repo")
    }
    with open(target_dir / "task_spec.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Initialize a pristine local git repository for the agent's worktree
    subprocess.run(f"git -C {target_dir} init -b main", shell=True, check=True, capture_output=True)
    subprocess.run(f"git -C {target_dir} config user.name 'Hermes Code Bot'", shell=True, check=True)
    subprocess.run(f"git -C {target_dir} config user.email 'codebot@hermes.local'", shell=True, check=True)
    
    # Initial commit of the problem spec
    subprocess.run(f"git -C {target_dir} add .", shell=True, check=True, capture_output=True)
    subprocess.run(f"git -C {target_dir} commit --allow-empty -m 'chore: initialize task workspace at base'", shell=True, check=True, capture_output=True)

    print(f"Workspace prepared at: {target_dir}")
    return target_dir

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="Task ID")
    parser.add_argument("--run-id", default="run_001", help="Run identifier")
    args = parser.parse_args()
    prepare_workspace(args.task, args.run_id)
