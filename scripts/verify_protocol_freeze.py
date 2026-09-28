#!/usr/bin/env python3
"""Block calibration until protocol and SUT identity are committed and remotely tagged."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PINNED_FILES = (
    "PROTOCOL_V2.json", "BENCHMARK_PROTOCOL.md", "BENCHMARK_SOURCES.md",
    "SYSTEM_UNDER_TEST.md", "environment-manifest.json",
    "benchmark-control/official_grader_status.json",
    "benchmark-manifest.json", "benchmark-cache-manifest.json",
    "system-under-test.json", "governance-manifest.json", "model-routing.json",
    "skill-inventory.json", "mcp-inventory.json", "tool-inventory.json",
)
HARNESS_FILES = (
    "scripts/chunked_benchmark_runner.py",
    "scripts/run_codebot_task.py",
    "scripts/collect_telemetry.py",
    "scripts/export_candidate_patch.py",
    "scripts/prepare_agent_workspace.py",
    "scripts/grade_with_official_verifier.py",
    "scripts/fresh_sandbox_regrade.py",
    "scripts/verify_official_graders.py",
    "scripts/verify_protocol_freeze.py",
    "scripts/build_report.py",
    "scripts/log_intervention.py",
    "scripts/verify_agent_sandbox.py",
)


class FreezeError(RuntimeError):
    pass


def command(args, *, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise FreezeError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_freeze(run_id, repo=REPO_DIR, check_remote=True):
    repo = Path(repo).resolve()
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id):
        raise FreezeError("INVALID_RUN_ID")
    if run_id == "run_001" or (repo / "runs" / run_id).exists() or (repo / "agent-workspaces" / run_id).exists():
        raise FreezeError("RUN_ID_ALREADY_USED")
    protocol_path = repo / "PROTOCOL_V2.json"
    if not protocol_path.is_file():
        raise FreezeError("PROTOCOL_V2_MISSING")
    protocol = json.loads(protocol_path.read_text())
    tag = protocol["protocol_tag"]
    git = lambda *args: command(["git", *args], cwd=repo)
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise FreezeError("GIT_NOT_CLEAN")
    if git("cat-file", "-t", tag) != "tag":
        raise FreezeError("PROTOCOL_TAG_NOT_ANNOTATED")
    frozen_sha = git("rev-parse", f"{tag}^{{commit}}")
    head = git("rev-parse", "HEAD")
    if frozen_sha != head:
        raise FreezeError("HEAD_DIFFERS_FROM_FROZEN_PROTOCOL_COMMIT")
    for name in PINNED_FILES + HARNESS_FILES:
        if not git("ls-tree", "--name-only", frozen_sha, "--", name):
            raise FreezeError(f"UNCOMMITTED_PIN: {name}")
        if name != "PROTOCOL_V2.json" and sha256(repo / name) != protocol["file_sha256"][name]:
            raise FreezeError(f"FROZEN_FILE_HASH_MISMATCH: {name}")
    if git("diff", "--name-only", frozen_sha, head, "--", *(PINNED_FILES + HARNESS_FILES)):
        raise FreezeError("FROZEN_FILES_CHANGED_AFTER_TAG")
    if protocol["max_turns"] != 60:
        raise FreezeError("TURN_BUDGET_CHANGED")
    if protocol["approval_mode"] != "off" or protocol["yolo_mode"] is not True:
        raise FreezeError("APPROVAL_POLICY_CHANGED")
    if command(["hermes", "--version"], cwd=repo).splitlines()[0] != protocol["hermes_version"]:
        raise FreezeError("HERMES_VERSION_DRIFT")
    for name, spec in protocol["external_sha256"].items():
        if sha256(spec["path"]) != spec["sha256"]:
            raise FreezeError(f"SUT_CONFIG_DRIFT: {name}")
    for name, spec in protocol["external_git"].items():
        actual = command(["git", "-C", spec["path"], "rev-parse", "HEAD"], cwd=repo)
        if actual != spec["sha"]:
            raise FreezeError(f"SUT_GIT_DRIFT: {name}")
        if command(["git", "-C", spec["path"], "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo):
            raise FreezeError(f"SUT_GIT_DIRTY: {name}")
    if check_remote:
        remote_tag = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}^{{}}")
        if not remote_tag or remote_tag.split()[0] != frozen_sha:
            raise FreezeError("REMOTE_PROTOCOL_TAG_MISMATCH")
        branch = git("branch", "--show-current")
        remote_head = git("ls-remote", "--heads", "origin", branch)
        if not remote_head or remote_head.split()[0] != head:
            raise FreezeError("REMOTE_BRANCH_HEAD_MISMATCH")
    return {"status": "PASS", "run_id": run_id, "protocol_tag": tag,
            "protocol_sha": frozen_sha, "head_sha": head}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(verify_freeze(args.run_id), indent=2))
