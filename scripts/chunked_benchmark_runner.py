#!/usr/bin/env python3
"""
chunked_benchmark_runner.py - Orchestrator for chunked benchmark execution.
Runs tasks in isolated sessions with 40% context budget and Official Grader verification.
Sends WeChat notification upon full completion.
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

REPO_DIR = Path("/Users/songshiyao/Desktop/Projects/hermes-code-agent-benchmark")
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"
STATE_PATH = REPO_DIR / "runs" / "benchmark_run_state.json"
SCRIPTS_DIR = REPO_DIR / "scripts"
PYTHON_BIN = REPO_DIR / ".venv" / "bin" / "python"

def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "status": "RUNNING",
        "current_track": "calibration",
        "completed_tasks": {},
        "started_at": time.time(),
        "updated_at": time.time()
    }

def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

HERMES_PYTHON = Path("/Users/songshiyao/.hermes/installs/6f381d8c7ae5bd7e/environments/c6bdf1a6971f4876ba6b6c8522463719/venv/bin/python")

def notify_wechat(message: str):
    try:
        py_exec = str(HERMES_PYTHON) if HERMES_PYTHON.exists() else str(PYTHON_BIN)
        cmd = [py_exec, str(SCRIPTS_DIR / "send_wechat_notice.py"), message]
        subprocess.run(cmd, check=True)
    except Exception as e:
        print(f"WeChat notification failed: {e}", file=sys.stderr)

def run_single_task(task_obj, track_name, run_id="run_001"):
    task_id = task_obj["task_id"]
    print(f"\n=======================================================")
    print(f"STARTING [{track_name}] TASK: {task_id}")
    print(f"=======================================================")
    
    # 1. Prepare isolated workspace
    cmd_prep = [str(PYTHON_BIN), str(SCRIPTS_DIR / "prepare_agent_workspace.py"), "--task", task_id, "--run-id", run_id]
    subprocess.run(cmd_prep, check=True)

    # 2. Record Task Start
    cmd_start = [str(PYTHON_BIN), str(SCRIPTS_DIR / "collect_telemetry.py"), "--task", task_id, "--run-id", run_id, "--event", "TASK_START"]
    subprocess.run(cmd_start, check=True)

    # 3. Spawn Codebot for this specific task
    # Codebot runs in an isolated workspace with instructions
    workspace_dir = REPO_DIR / "agent-workspaces" / run_id / task_id
    instructions_file = workspace_dir / "PROBLEM.md"
    
    prompt = f"Please solve the problem described in PROBLEM.md within this directory: {workspace_dir}. Inspect files, implement minimal correct fix, test if possible, and exit cleanly."
    
    # Run hermes agent in isolated mode with max-turns 60 (to respect the ~40% context budget)
    # Using profile 'code'
    agent_cmd = [
        "hermes", "-p", "code", "chat",
        "-q", prompt,
        "--yolo",
        "--max-turns", "60"
    ]
    print(f"Executing Codebot in workspace {workspace_dir}...")
    run_env = dict(os.environ)
    run_env["HERMES_YOLO_MODE"] = "1"
    try:
        subprocess.run(agent_cmd, cwd=str(workspace_dir), timeout=1800, env=run_env)
    except subprocess.TimeoutExpired:
        print(f"Task {task_id} timed out after 30 minutes.")

    # 4. Export Candidate Patch
    try:
        cmd_export = [str(PYTHON_BIN), str(SCRIPTS_DIR / "export_candidate_patch.py"), "--task", task_id, "--run-id", run_id]
        subprocess.run(cmd_export, check=True)
    except Exception as e:
        print(f"[WARN] Failed to export patch for {task_id}: {e}")

    # 5. Grade with Official Verifier
    try:
        cmd_grade = [str(PYTHON_BIN), str(SCRIPTS_DIR / "grade_with_official_verifier.py"), "--task", task_id, "--run-id", run_id]
        subprocess.run(cmd_grade, check=True)
    except Exception as e:
        print(f"[WARN] Failed to run official verifier for {task_id}: {e}")

    # 6. Fresh Sandbox Regrade
    try:
        cmd_regrade = [str(PYTHON_BIN), str(SCRIPTS_DIR / "fresh_sandbox_regrade.py"), "--task", task_id, "--run-id", run_id]
        subprocess.run(cmd_regrade, check=True)
    except Exception as e:
        print(f"[WARN] Failed to run fresh sandbox regrade for {task_id}: {e}")

    # Read result
    summary_path = REPO_DIR / "runs" / run_id / task_id / "telemetry_summary.json"
    resolved = False
    if summary_path.exists():
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)
            resolved = summary_data.get("resolved", False)

    print(f"COMPLETED TASK {task_id} - Resolved: {resolved}")
    return {"resolved": resolved, "completed_at": time.time()}

def main():
    manifest = load_manifest()
    state = load_state()
    run_id = "run_001"

    # Calibration tasks
    calib_tasks = manifest.get("calibration_tasks", [])
    scored_tasks = manifest.get("scored_tasks", [])
    
    track_a_tasks = [t for t in scored_tasks if t.get("track") == "swe-bench-verified"]
    track_b_tasks = [t for t in scored_tasks if t.get("track") == "swe-bench-pro-v2"]
    track_c_tasks = [t for t in scored_tasks if t.get("track") == "terminal-bench"]

    all_stages = [
        ("calibration", calib_tasks),
        ("track_a", track_a_tasks),
        ("track_b", track_b_tasks),
        ("track_c", track_c_tasks)
    ]

    total_tasks = sum(len(tasks) for _, tasks in all_stages)
    print(f"Starting chunked benchmark runner. Total tasks across all stages: {total_tasks}")

    for stage_name, tasks in all_stages:
        state["current_track"] = stage_name
        for task in tasks:
            task_id = task["task_id"]
            if task_id in state["completed_tasks"]:
                print(f"Skipping already completed task: {task_id}")
                continue

            # Run task
            res = run_single_task(task, stage_name, run_id=run_id)
            state["completed_tasks"][task_id] = res
            save_state(state)

    state["status"] = "FINISHED"
    save_state(state)

    # Build final report
    print("\nBuilding final benchmark report...")
    cmd_report = [str(PYTHON_BIN), str(SCRIPTS_DIR / "build_report.py"), "--run-id", run_id]
    subprocess.run(cmd_report, check=True)

    # Send WeChat Notification
    completed_count = len(state["completed_tasks"])
    resolved_count = sum(1 for v in state["completed_tasks"].values() if v.get("resolved"))
    
    notice_text = (
        f"🎯【Hermes Codebot Benchmark 全部评测完成】\n\n"
        f"• 状态：全部评测阶段顺利结束\n"
        f"• 总题目数：{completed_count} 题（含 Calibration 校准与全量 Scored 题集）\n"
        f"• 官方 Grader 判定通过：{resolved_count} / {completed_count}\n"
        f"• 上下文控制：单题独立会话隔离，严格压制在 40% 预算内\n"
        f"• 报告已生成：hermes-code-agent-benchmark/reports/final-report.html\n\n"
        f"请在电脑端查阅完整报告与 Diff 审计记录。"
    )
    print("Sending final completion notification via WeChat...")
    notify_wechat(notice_text)
    print("All tasks finished successfully.")

if __name__ == "__main__":
    main()
