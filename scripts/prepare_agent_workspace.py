#!/usr/bin/env python3
"""Prepare the actual task base, never a stand-in repository containing only a prompt."""

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
WORKSPACES_ROOT = REPO_DIR / "agent-workspaces"
RUNS_ROOT = REPO_DIR / "runs"
UPSTREAM = {
    "swe-bench-pro-v2": "swe-bench-pro-v2",
    "terminal-bench": "terminal-bench",
}


def command(args, *, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def git(repo, *args):
    return command(["git", "-C", str(repo), *args])


def task_record(task_id):
    manifest = json.loads((REPO_DIR / "benchmark-manifest.json").read_text())
    tasks = manifest["calibration_tasks"] + manifest["scored_tasks"]
    return next((task for task in tasks if task["task_id"] == task_id), None)


def upstream_task_dir(task):
    cache = json.loads((REPO_DIR / "benchmark-cache-manifest.json").read_text())
    entry = next(a for a in cache["cached_artifacts"] if a["artifact"] == UPSTREAM[task["track"]])
    root = Path(entry["disk_path"]).resolve(strict=True)
    if git(root, "rev-parse", "HEAD") != task["upstream_sha"]:
        raise RuntimeError("UPSTREAM_SHA_MISMATCH")
    if git(root, "status", "--porcelain=v1"):
        raise RuntimeError("UPSTREAM_DIRTY")
    task_dir = Path(task["task_dir"]).resolve(strict=True)
    if not task_dir.is_relative_to(root) or task_dir.name != task["task_id"]:
        raise RuntimeError("TASK_SOURCE_MISMATCH")
    return task_dir


def docker_workspace(task, repo):
    task_dir = upstream_task_dir(task)
    config = tomllib.loads((task_dir / "task.toml").read_text())
    if task["track"] == "swe-bench-pro-v2":
        image = config["environment"]["docker_image"]
    else:
        image = f"benchmark-base-{task['task_id']}:{task['upstream_sha'][:12]}"
        command(["docker", "build", "-q", "-t", image, str(task_dir / "environment")])
    image_id = command(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    container = command(["docker", "create", "--entrypoint", "/bin/sh", image, "-c", "true"])
    try:
        repo.mkdir(parents=True)
        command(["docker", "cp", f"{container}:/app/.", str(repo)])
    finally:
        command(["docker", "rm", "-f", container])
    # Existing source Git is kept. Non-Git tasks use an exact /app snapshot commit.
    if not (repo / ".git").exists():
        command(["git", "init", "-q", "-b", "main", str(repo)])
        git(repo, "config", "user.name", "Benchmark Base Snapshot")
        git(repo, "config", "user.email", "benchmark-base@localhost")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "benchmark: pristine task image /app snapshot")
    return {"kind": "official_agent_image", "task_dir": str(task_dir),
            "image": image, "image_id": image_id}


def prepare_workspace(task_id, run_id):
    if not run_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in run_id):
        raise ValueError("invalid run_id")
    task = task_record(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not in committed manifest")
    wrapper = WORKSPACES_ROOT / run_id / task_id
    repo = wrapper / "repo"
    evidence = RUNS_ROOT / run_id / "tasks" / task_id
    if wrapper.exists() or evidence.exists():
        raise RuntimeError("WORKSPACE_OR_EVIDENCE_ALREADY_EXISTS")
    wrapper.mkdir(parents=True)
    if task["track"] == "swe-bench-verified":
        expected_repo = task["repo"]
        if not expected_repo or not task.get("base_commit"):
            raise RuntimeError("MISSING_GIT_BASE")
        command(["git", "clone", "--quiet", "--no-checkout",
                 f"https://github.com/{expected_repo}.git", str(repo)])
        git(repo, "checkout", "--quiet", "--detach", task["base_commit"])
        source = {"kind": "git", "repo": expected_repo,
                  "expected_base_sha": task["base_commit"]}
    else:
        source = docker_workspace(task, repo)
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve():
        raise RuntimeError("WRONG_REPO_ROOT")
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeError(f"DIRTY_BASE: {status[:500]}")
    base_sha = git(repo, "rev-parse", "HEAD")
    if task["track"] == "swe-bench-verified" and base_sha != task["base_commit"]:
        raise RuntimeError("BASE_SHA_MISMATCH")
    evidence.mkdir(parents=True)
    (wrapper / "PROBLEM.md").write_text(task.get("problem_statement") or task.get("instruction") or "")
    record = {
        "task_id": task_id, "track": task["track"], "run_id": run_id,
        "workspace": str(wrapper.resolve()), "repo_root": str(repo.resolve()),
        "base_sha": base_sha, "base_tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "initial_head": base_sha, "initial_status": status,
        "expected_repo": source, "upstream_sha": task["upstream_sha"],
    }
    (evidence / "workspace-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    return repo


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(prepare_workspace(args.task, args.run_id))
