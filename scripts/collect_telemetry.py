#!/usr/bin/env python3
"""Record harness events and derive usage only from Hermes stream-json output."""

import json
import time
import argparse
import shlex
from collections import Counter
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

    def record_event(self, event_type, details=None, *, source="benchmark_harness", timestamp=None):
        event = {
            "timestamp": time.time() if timestamp is None else timestamp,
            "event": event_type,
            "source": source,
            "details": details or {},
        }
        with self.timeline_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def ingest_stream(self, stdout_path, stderr_path, *, exit_code, duration_ms, timed_out=False):
        """Keep the raw files intact; derive only fields exposed by Hermes stream-json.

        The protocol lacks Goal-loop and reviewer lifecycle events. Its emitter
        also defaults missing token counters to zero, so all-zero is unknown.
        """
        stdout_path = Path(stdout_path)
        stderr_path = Path(stderr_path)
        events = []
        error = None
        try:
            for line_number, line in enumerate(stdout_path.read_text(encoding="utf-8").splitlines(), 1):
                event = json.loads(line)
                if not isinstance(event, dict) or event.get("type") not in {
                    "system", "text", "tool_use", "tool_result", "result"
                }:
                    raise ValueError(f"unexpected event on line {line_number}")
                events.append(event)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            error = str(exc)

        inits = [event for event in events if event.get("type") == "system" and event.get("subtype") == "init"]
        results = [event for event in events if event.get("type") == "result"]
        complete = (
            error is None and not timed_out and exit_code is not None
            and len(inits) == 1 and len(results) == 1
            and events[0] is inits[0] and events[-1] is results[0]
            and isinstance(results[0].get("exit_code"), int)
            and results[0]["exit_code"] == exit_code
            and inits[0].get("session_id") == results[0].get("session_id")
        )
        if not complete and error is None:
            error = "missing, incomplete, or inconsistent Hermes stream-json envelope"

        calls = [event for event in events if event.get("type") == "tool_use" and isinstance(event.get("name"), str)]
        names = [event["name"] for event in calls]

        def usage(selected, observable=True):
            if selected:
                status = "USED"
            elif not complete or not observable:
                status = "TELEMETRY_UNAVAILABLE"
            else:
                status = "NOT_USED"
            return {"status": status, "count": len(selected), "by_name": dict(Counter(selected)),
                    "source": "hermes-stream.jsonl" if selected else None}

        tool_usage = usage(names)
        skill_usage = usage([name for name in names if name.startswith("skill_")])
        mcp_usage = usage([name for name in names if name.startswith("mcp__")])
        kanban_usage = usage([name for name in names if name.startswith("kanban_")])
        # A delegation tool call alone cannot establish an independent review.
        goal_usage = usage([], observable=False)
        review_usage = usage([], observable=False)

        tokens = "NOT_AVAILABLE"
        if complete:
            raw_tokens = results[0].get("tokens")
            if isinstance(raw_tokens, dict) and any(
                isinstance(value, int) and value > 0 for value in raw_tokens.values()
            ):
                tokens = {
                    key: value if isinstance(value, int) and not isinstance(value, bool) and value > 0
                    else "NOT_AVAILABLE"
                    for key, value in raw_tokens.items()
                }

        raw_tokens = results[0].get("tokens") if complete else None

        def measured_token(name):
            # Hermes' stream emitter substitutes zero for missing counters.
            value = raw_tokens.get(name) if isinstance(raw_tokens, dict) else None
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else "NOT_AVAILABLE"

        model_usage = {
            "model": (inits[0].get("model") or "NOT_AVAILABLE") if complete else "NOT_AVAILABLE",
            "calls": "NOT_AVAILABLE",
            "input_tokens": measured_token("input"),
            "output_tokens": measured_token("output"),
            "cached_tokens": measured_token("cache_read"),
            "cache_write_tokens": measured_token("cache_write"),
            "total_tokens": measured_token("total"),
            "reasoning_tokens": "NOT_AVAILABLE",
            "cost": "NOT_AVAILABLE",
            "source": "hermes-stream.jsonl" if complete else "TELEMETRY_UNAVAILABLE",
        }

        summary = {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "trace_status": "COMPLETE" if complete else "TELEMETRY_UNAVAILABLE",
            "trace_error": error,
            "raw_stdout": str(stdout_path),
            "raw_stderr": str(stderr_path),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "session_id": inits[0].get("session_id") if complete else "NOT_AVAILABLE",
            "model": model_usage["model"],
            "tokens": tokens,
            "model_usage": model_usage,
            "tool_usage": tool_usage,
            "skill_usage": skill_usage,
            "mcp_usage": mcp_usage,
            "goal_usage": goal_usage,
            "kanban_usage": kanban_usage,
            "review_usage": review_usage,
        }
        (self.task_dir / "task-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        for name, data in (("tool-usage.json", tool_usage), ("skill-usage.json", skill_usage),
                           ("mcp-usage.json", mcp_usage), ("model-usage.json", model_usage)):
            (self.task_dir / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
        for event in events:
            event_type = event.get("type")
            if event_type not in {"tool_use", "tool_result"}:
                continue
            details = {"name": event.get("name", "NOT_AVAILABLE")}
            if event.get("tool_call_id"):
                details["tool_call_id"] = event["tool_call_id"]
            if event_type == "tool_result":
                details["is_error"] = event.get("is_error", "NOT_AVAILABLE")
                details["duration_ms"] = event.get("duration_ms", "NOT_AVAILABLE")
            raw_timestamp = event.get("timestamp")
            timestamp = raw_timestamp / 1000 if isinstance(raw_timestamp, (int, float)) else None
            lifecycle = "TOOL_CALL" if event_type == "tool_use" else "TOOL_RESULT"
            self.record_event(lifecycle, details, source="hermes-stream-json", timestamp=timestamp)
            if event_type != "tool_use":
                continue
            name = event["name"]
            if name.startswith("skill_"):
                self.record_event("SKILL_INVOKED", details, source="hermes-stream-json", timestamp=timestamp)
            if name.startswith("mcp__"):
                self.record_event("MCP_CALL", details, source="hermes-stream-json", timestamp=timestamp)
            if name.startswith("kanban_"):
                self.record_event("KANBAN_TOOL_CALL", details, source="hermes-stream-json", timestamp=timestamp)
            args = event.get("input")
            command = args.get("command") if isinstance(args, dict) else None
            if isinstance(command, str):
                try:
                    words = shlex.split(command)
                except ValueError:
                    words = []
                if words and words[0] == "git" and len(words) > 1:
                    verb = words[1]
                    if verb in {"status", "commit", "diff"}:
                        self.record_event(f"GIT_{verb.upper()}", details,
                                          source="hermes-stream-json", timestamp=timestamp)
                if words and (words[0] == "pytest" or
                              (words[0] in {"go", "cargo"} and len(words) > 1 and words[1] == "test")):
                    self.record_event("TEST_START", {**details, "exit_code": "NOT_AVAILABLE"},
                                      source="hermes-stream-json", timestamp=timestamp)
        if complete and tokens != "NOT_AVAILABLE":
            result_timestamp = results[0].get("timestamp")
            self.record_event("MODEL_USAGE", model_usage, source="hermes-stream-json",
                              timestamp=result_timestamp / 1000 if isinstance(result_timestamp, (int, float)) else None)
        self.record_event("HERMES_PROCESS_END", {
            "exit_code": exit_code, "duration_ms": duration_ms,
            "trace_status": summary["trace_status"], "timed_out": timed_out,
        })
        return summary

    def finalize_summary(self, result_dict):
        summary_path = self.task_dir / "task-summary.json"
        summary_path.write_text(json.dumps(result_dict, indent=2), encoding="utf-8")
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
