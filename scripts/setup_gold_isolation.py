#!/usr/bin/env python3
"""
setup_gold_isolation.py - Extract and isolate reference solutions / oracles into benchmark-control/private-oracle.
Ensures strictly zero presence of gold solutions in agent workspaces.
"""

import os
import sys
import json
import shutil
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"
ORACLE_DIR = REPO_DIR / "benchmark-control" / "private-oracle"

def setup_isolation():
    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    all_tasks = manifest["calibration_tasks"] + manifest["scored_tasks"]
    
    # Track A: SWE-bench Verified
    import datasets
    ds = datasets.load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    hf_map = {str(dict(row)["instance_id"]): dict(row) for row in ds}  # type: ignore

    swe_oracle_dir = ORACLE_DIR / "swe-bench"
    swe_oracle_dir.mkdir(parents=True, exist_ok=True)

    for task in all_tasks:
        if task["track"] == "swe-bench-verified":
            t_id = task["task_id"]
            if t_id in hf_map:
                row = hf_map[t_id]
                oracle_file = swe_oracle_dir / f"{t_id}.patch"
                oracle_file.write_text(row.get("patch", ""))

    # Track B: SWE-bench Pro V2
    pro_oracle_dir = ORACLE_DIR / "swe-bench-pro"
    pro_oracle_dir.mkdir(parents=True, exist_ok=True)
    pro_tasks_dir = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check/swe-bench-pro/v2/tasks")

    for task in all_tasks:
        if task["track"] == "swe-bench-pro-v2":
            t_id = task["task_id"]
            src_sol = pro_tasks_dir / t_id / "solution"
            dest_sol = pro_oracle_dir / t_id
            if src_sol.exists():
                shutil.copytree(src_sol, dest_sol, dirs_exist_ok=True)

    # Track C: Terminal-Bench
    tb_oracle_dir = ORACLE_DIR / "terminal-bench"
    tb_oracle_dir.mkdir(parents=True, exist_ok=True)
    tb_tasks_dir = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check/terminal-bench/tasks")

    for task in all_tasks:
        if task["track"] == "terminal-bench":
            t_id = task["task_id"]
            src_sol = tb_tasks_dir / t_id / "solution"
            dest_sol = tb_oracle_dir / t_id
            if src_sol.exists():
                shutil.copytree(src_sol, dest_sol, dirs_exist_ok=True)

    # Write access control notice
    notice = (
        "# PRIVATE ORACLE DIRECTORY\n\n"
        "STRICTLY FORBIDDEN FROM AGENT ACCESS, PROMPT INGESTION, OR HARNESS CONTEXT.\n"
        "Used solely by control-plane scripts during prior validator verification.\n"
    )
    (ORACLE_DIR / "README.md").write_text(notice)

    print(f"Isolated oracles extracted to {ORACLE_DIR} successfully.")

if __name__ == "__main__":
    setup_isolation()
