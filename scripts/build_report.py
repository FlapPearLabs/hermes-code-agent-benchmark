#!/usr/bin/env python3
"""
build_report.py - Generate interim and final benchmark reports from telemetry and official grader results.
Adheres to Sections 50, 51, 52 of Benchmark Protocol.
"""

import os
import sys
import json
import argparse
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"
RUNS_ROOT = REPO_DIR / "runs"
REPORTS_DIR = REPO_DIR / "reports"

def generate_report(run_id="run_001", interim_count=None):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    tasks_dir = RUNS_ROOT / run_id / "tasks"
    scored_tasks = manifest["scored_tasks"]

    total = len(scored_tasks)
    completed = 0
    resolved = 0
    fresh_resolved = 0
    human_interventions = 0

    track_results = {
        "swe-bench-verified": {"total": 0, "resolved": 0},
        "swe-bench-pro-v2": {"total": 0, "resolved": 0},
        "terminal-bench": {"total": 0, "resolved": 0}
    }

    for task in scored_tasks:
        t_id = task["task_id"]
        t_dir = tasks_dir / t_id
        track = task["track"]
        track_results[track]["total"] += 1

        if (t_dir / "task-summary.json").exists():
            completed += 1
            summary = json.loads((t_dir / "task-summary.json").read_text())
            if summary.get("resolved"):
                resolved += 1
                track_results[track]["resolved"] += 1
            if summary.get("fresh_sandbox_resolved"):
                fresh_resolved += 1

        if (t_dir / "human-interventions.jsonl").exists():
            lines = [l for l in (t_dir / "human-interventions.jsonl").read_text().splitlines() if l.strip()]
            human_interventions += len(lines)

    lines = [
        f"# Benchmark Report: {run_id}",
        "",
        "## Summary Metrics",
        f"- **Total Scored Tasks**: {total}",
        f"- **Completed Tasks**: {completed}",
        f"- **Official Grader Resolved**: {resolved}/{completed} ({resolved/max(completed,1):.1%})",
        f"- **Fresh Sandbox Resolved**: {fresh_resolved}/{completed} ({fresh_resolved/max(completed,1):.1%})",
        f"- **Human Interventions**: {human_interventions} ({human_interventions/max(completed,1):.2f}/task)",
        "",
        "## Track Results",
    ]
    for track, data in track_results.items():
        lines.append(f"- **{track}**: {data['resolved']}/{data['total']}")

    content = "\n".join(lines) + "\n"

    if interim_count:
        report_path = REPORTS_DIR / f"INTERIM_REPORT_{interim_count:02d}.md"
    else:
        report_path = REPORTS_DIR / "FINAL_BENCHMARK_REPORT.md"

    report_path.write_text(content)
    print(f"Report written to {report_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="run_001")
    parser.add_argument("--interim", type=int, help="Interim milestone (5, 10, 15, 20)")
    args = parser.parse_args()
    generate_report(args.run_id, args.interim)
