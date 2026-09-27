#!/usr/bin/env python3
"""
select_tasks.py - Deterministic task selection for Hermes Code Agent Benchmark (Protocol v1).

Sampling Rules:
- Track A: SWE-bench Verified (6 tasks: 2 Easy, 2 Medium, 2 Hard based on canonical 'difficulty')
- Track B: SWE-bench Pro V2 (10 tasks: 6 General V2, 4 Hard-51)
- Track C: Terminal-Bench (4 tasks: sandboxed CLI/dev tasks, filtered for hardware/auth feasibility)
- Calibration: 1 non-scored calibration task per track (3 total)
"""

import os
import sys
import json
import random
import hashlib
from pathlib import Path

SEED = 20260927
random.seed(SEED)

REPO_DIR = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_DIR / "benchmarks"

# Upstream metadata
UPSTREAM_META = {
    "swe-bench": {
        "url": "https://github.com/princeton-nlp/SWE-bench.git",
        "exact_sha": "02e7a74ffd0b707aab73d203fe87bdc7c76afc8e",
        "dataset": "princeton-nlp/SWE-bench_Verified",
        "dataset_version": "test"
    },
    "swe-bench-pro": {
        "url": "https://github.com/scaleapi/SWE-bench_Pro-os.git",
        "exact_sha": "66f92766bba642462d4bbe5479e83f91f9211862",
        "tag": "v2.0.0",
        "dataset": "ScaleAI/SWE-bench_Pro",
        "dataset_version": "v2.0.0"
    },
    "terminal-bench": {
        "url": "https://github.com/harbor-framework/terminal-bench.git",
        "exact_sha": "4def1f367467b34b18e0dbdc086400ba71c3e037",
        "dataset": "terminal-bench/terminal-bench",
        "dataset_version": "git:4def1f367467b34b18e0dbdc086400ba71c3e037"
    }
}

def select_swe_bench_verified():
    import datasets
    # Load dataset
    ds = datasets.load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    
    easy_pool = []
    med_pool = []
    hard_pool = []
    
    for raw_row in ds:
        row = dict(raw_row)  # type: ignore
        diff = row.get("difficulty", "")
        item = {
            "track": "swe-bench-verified",
            "task_id": str(row["instance_id"]),
            "repo": str(row["repo"]),
            "base_commit": str(row["base_commit"]),
            "difficulty": str(diff),
            "container_image": f"swebench/sweb.eval.x86_64.{str(row['instance_id']).lower()}:v1",
            "problem_statement": str(row["problem_statement"]),
            "FAIL_TO_PASS": row.get("FAIL_TO_PASS", []),
            "PASS_TO_PASS": row.get("PASS_TO_PASS", []),
            "upstream_source": UPSTREAM_META["swe-bench"]["url"],
            "upstream_sha": UPSTREAM_META["swe-bench"]["exact_sha"]
        }
        if diff == "<15 min fix":
            easy_pool.append(item)
        elif diff == "15 min - 1 hour":
            med_pool.append(item)
        elif diff in ("1-4 hours", ">4 hours"):
            hard_pool.append(item)

    # Sort deterministically
    easy_pool.sort(key=lambda x: x["task_id"])
    med_pool.sort(key=lambda x: x["task_id"])
    hard_pool.sort(key=lambda x: x["task_id"])

    rng = random.Random(SEED)
    selected_easy = rng.sample(easy_pool, 2)
    selected_med = rng.sample(med_pool, 2)
    selected_hard = rng.sample(hard_pool, 2)

    # Pick 1 calibration instance (distinct from selected)
    remaining_easy = [x for x in easy_pool if x not in selected_easy]
    calibration_task = rng.sample(remaining_easy, 1)[0]
    calibration_task["is_calibration"] = True

    selected = selected_easy + selected_med + selected_hard
    for s in selected:
        s["is_calibration"] = False

    return selected, calibration_task

def select_swe_bench_pro():
    pro_tasks_dir = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check/swe-bench-pro/v2/tasks")
    hard51_file = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check/swe-bench-pro/v2/hard51_ids.txt")
    
    with open(hard51_file) as f:
        hard_ids = set(line.strip() for line in f if line.strip())

    all_task_dirs = sorted([d.name for d in pro_tasks_dir.iterdir() if d.is_dir()])
    
    general_pool = [t for t in all_task_dirs if t not in hard_ids]
    hard_pool = [t for t in all_task_dirs if t in hard_ids]

    rng = random.Random(SEED + 100)
    selected_general_ids = rng.sample(general_pool, 6)
    selected_hard_ids = rng.sample(hard_pool, 4)

    # Pick 1 calibration instance
    remaining_general = [t for t in general_pool if t not in selected_general_ids]
    calib_id = rng.sample(remaining_general, 1)[0]

    def build_pro_item(t_id, is_hard=False, is_calib=False):
        t_path = pro_tasks_dir / t_id
        instruction = ""
        inst_file = t_path / "instruction.md"
        if inst_file.exists():
            instruction = inst_file.read_text(errors="ignore")
        return {
            "track": "swe-bench-pro-v2",
            "task_id": t_id,
            "is_hard": is_hard,
            "is_calibration": is_calib,
            "upstream_source": UPSTREAM_META["swe-bench-pro"]["url"],
            "upstream_sha": UPSTREAM_META["swe-bench-pro"]["exact_sha"],
            "task_dir": str(t_path),
            "instruction": instruction
        }

    selected = [build_pro_item(t, is_hard=False) for t in selected_general_ids] + \
               [build_pro_item(t, is_hard=True) for t in selected_hard_ids]
    calib_task = build_pro_item(calib_id, is_hard=False, is_calib=True)

    return selected, calib_task

def select_terminal_bench():
    tb_tasks_dir = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check/terminal-bench/tasks")
    all_tasks = sorted([d.name for d in tb_tasks_dir.iterdir() if d.is_dir() and (d / "task.toml").exists()])

    # Exclusion rules:
    # Exclude tasks known to require external GPU/cloud API credentials
    excluded_keywords = ["gpu", "cuda", "aws", "gcp", "azure", "openai-key", "anthropic-key"]
    
    feasible_pool = []
    for t_id in all_tasks:
        t_path = tb_tasks_dir / t_id
        task_toml = (t_path / "task.toml").read_text(errors="ignore").lower()
        if any(k in task_toml or k in t_id.lower() for k in excluded_keywords):
            continue
        feasible_pool.append(t_id)

    rng = random.Random(SEED + 200)
    selected_ids = rng.sample(feasible_pool, 4)
    remaining = [t for t in feasible_pool if t not in selected_ids]
    calib_id = rng.sample(remaining, 1)[0]

    def build_tb_item(t_id, is_calib=False):
        t_path = tb_tasks_dir / t_id
        instruction = ""
        inst_file = t_path / "instruction.md"
        if inst_file.exists():
            instruction = inst_file.read_text(errors="ignore")
        return {
            "track": "terminal-bench",
            "task_id": t_id,
            "is_calibration": is_calib,
            "upstream_source": UPSTREAM_META["terminal-bench"]["url"],
            "upstream_sha": UPSTREAM_META["terminal-bench"]["exact_sha"],
            "task_dir": str(t_path),
            "instruction": instruction
        }

    selected = [build_tb_item(t) for t in selected_ids]
    calib_task = build_tb_item(calib_id, is_calib=True)

    return selected, calib_task

def main():
    print(f"Executing deterministic selection with SEED={SEED}...")
    
    swe_tasks, swe_calib = select_swe_bench_verified()
    pro_tasks, pro_calib = select_swe_bench_pro()
    tb_tasks, tb_calib = select_terminal_bench()

    scored_tasks = swe_tasks + pro_tasks + tb_tasks
    calibration_tasks = [swe_calib, pro_calib, tb_calib]

    manifest = {
        "benchmark_protocol_version": "protocol-v1",
        "selection_seed": SEED,
        "selection_script_sha256": "",
        "upstream_sources": UPSTREAM_META,
        "total_scored_tasks": len(scored_tasks),
        "total_calibration_tasks": len(calibration_tasks),
        "calibration_tasks": calibration_tasks,
        "scored_tasks": scored_tasks
    }

    # Calculate script sha
    script_bytes = Path(__file__).read_bytes()
    manifest["selection_script_sha256"] = hashlib.sha256(script_bytes).hexdigest()

    manifest_path = REPO_DIR / "benchmark-manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Task selection complete!")
    print(f"- SWE-bench Verified: {len(swe_tasks)} scored + 1 calibration")
    print(f"- SWE-bench Pro V2: {len(pro_tasks)} scored + 1 calibration")
    print(f"- Terminal-Bench: {len(tb_tasks)} scored + 1 calibration")
    print(f"Total: {len(scored_tasks)} scored tasks written to {manifest_path}")

if __name__ == "__main__":
    main()
