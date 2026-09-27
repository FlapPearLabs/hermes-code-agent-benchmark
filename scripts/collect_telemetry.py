#!/usr/bin/env python3
"""
collect_telemetry.py - Mechanically record all events, tool calls, reviews, and metrics per task.
Adheres to Sections 30, 31, 32 of Benchmark Protocol.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_DIR / "runs"

class TaskTelemetryCollector:
    def __init__(self, task_id, run_id="run_001"):
        self.task_id = task_id
        self.run_id = run_id
        self.task_dir = RUNS_ROOT / run_id / "tasks" / task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.timeline_path = self.task_dir / "timeline.jsonl"
        self.init_structure()

    def init_structure(self):
        # Create initial placeholders if not existing
        files = [
            ("tool-usage.json", {}),
            ("skill-usage.json", {}),
            ("mcp-usage.json", {}),
            ("kanban-events.jsonl", ""),
            ("git-events.jsonl", ""),
            ("test-events.jsonl", ""),
            ("review-events.jsonl", ""),
            ("human-interventions.jsonl", ""),
            ("model-usage.json", {"model": "gemini-3.8-flash-tiered", "calls": 0, "input_tokens": 0, "output_tokens": 0})
        ]
        for fname, default_val in files:
            p = self.task_dir / fname
            if not p.exists():
                if isinstance(default_val, (dict, list)):
                    p.write_text(json.dumps(default_val, indent=2))
                else:
                    p.write_text(default_val)

        decision_log = self.task_dir / "decision-log.md"
        if not decision_log.exists():
            decision_log.write_text(f"# Decision Log: {self.task_id}\n\nTask initiated.\n")

    def record_event(self, event_type, details=None):
        event = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event_type,
            "details": details or {}
        }
        with open(self.timeline_path, "a") as f:
            f.write(json.dumps(event) + "\n")

    def finalize_summary(self, result_dict):
        summary_path = self.task_dir / "task-summary.json"
        summary_path.write_text(json.dumps(result_dict, indent=2))
        self.record_event("TASK_END", result_dict)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", default="run_001")
    parser.add_argument("--event", help="Record a specific event")
    parser.add_argument("--details", default="{}", help="Event details as JSON string")
    args = parser.parse_args()

    collector = TaskTelemetryCollector(args.task, args.run_id)
    if args.event:
        details = json.loads(args.details)
        collector.record_event(args.event, details)
    print(f"Telemetry initialized/updated for {args.task}")
