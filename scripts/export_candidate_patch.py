#!/usr/bin/env python3
"""
export_candidate_patch.py - Export unified git diff from agent worktree.
Saves patch to runs/<run_id>/tasks/<task_id>/patch.diff
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
WORKSPACES_ROOT = REPO_DIR / "agent-workspaces"
RUNS_ROOT = REPO_DIR / "runs"

def export_patch(task_id, run_id="run_001"):
    workspace_dir = WORKSPACES_ROOT / run_id / task_id
    if not workspace_dir.exists():
        raise FileNotFoundError(f"Workspace {workspace_dir} does not exist!")

    dest_dir = RUNS_ROOT / run_id / "tasks" / task_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Get git diff against base commit if available, else root commit / HEAD
    task_spec_path = workspace_dir / "task_spec.json"
    base_commit = None
    if task_spec_path.exists():
        try:
            with open(task_spec_path) as f:
                task_spec = json.load(f)
                base_commit = task_spec.get("base_commit")
        except Exception:
            pass

    if base_commit and subprocess.run(f"git -C {workspace_dir} rev-parse --verify {base_commit}", shell=True, capture_output=True).returncode == 0:
        cmd = f"git -C {workspace_dir} diff {base_commit}"
    else:
        res = subprocess.run(f"git -C {workspace_dir} rev-list --count HEAD", shell=True, capture_output=True, text=True)
        count = int(res.stdout.strip() or 1)

        if count > 1:
            # Diff against root commit
            root_commit = subprocess.run(f"git -C {workspace_dir} rev-list --max-parents=0 HEAD", shell=True, capture_output=True, text=True).stdout.strip()
            cmd = f"git -C {workspace_dir} diff {root_commit} HEAD"
        else:
            cmd = f"git -C {workspace_dir} diff HEAD"

    diff_res = subprocess.run(cmd, shell=True, capture_output=True)
    diff_bytes = diff_res.stdout

    patch_file = dest_dir / "patch.diff"
    patch_file.write_bytes(diff_bytes)

    # Also capture candidate commit SHA
    head_res = subprocess.run(f"git -C {workspace_dir} rev-parse HEAD", shell=True, capture_output=True)
    head_sha = head_res.stdout.decode('utf-8', errors='replace').strip()
    (dest_dir / "candidate_sha.txt").write_text(head_sha)

    print(f"Exported patch ({len(diff_bytes)} bytes) and SHA ({head_sha}) to {dest_dir}")
    return patch_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="Task ID")
    parser.add_argument("--run-id", default="run_001", help="Run identifier")
    args = parser.parse_args()
    export_patch(args.task, args.run_id)
