#!/usr/bin/env python3
"""Export the exact base-to-candidate tree diff, including untracked files."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
WORKSPACES_ROOT = REPO_DIR / "agent-workspaces"
RUNS_ROOT = REPO_DIR / "runs"


class PatchExportError(RuntimeError):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


def git(repo, *args, env=None, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env)
    if check and result.returncode:
        raise PatchExportError("BASE_DIVERGENCE", result.stderr.decode(errors="replace").strip())
    return result


def output(repo, *args, env=None):
    return git(repo, *args, env=env).stdout.strip().decode()


def _paths(raw):
    return [p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p]


def export_patch(task_id, run_id):
    if run_id == "run_001":
        raise PatchExportError("INVALID", "historical run_001 is immutable")
    dest = RUNS_ROOT / run_id / "tasks" / task_id
    manifest_path = dest / "workspace-manifest.json"
    if not manifest_path.is_file():
        raise PatchExportError("BASE_DIVERGENCE", "workspace manifest missing")
    manifest = json.loads(manifest_path.read_text())
    result_path = dest / "patch-export-result.json"
    patch_path = dest / "patch.diff"
    try:
        expected = (WORKSPACES_ROOT / run_id / task_id / "repo").resolve(strict=True)
        repo = Path(manifest["repo_root"]).resolve(strict=True)
        if repo != expected or manifest["task_id"] != task_id or manifest["run_id"] != run_id:
            raise PatchExportError("BASE_DIVERGENCE", "workspace identity mismatch")
        if Path(output(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
            raise PatchExportError("BASE_DIVERGENCE", "worktree points to wrong repository")
        base = manifest["base_sha"]
        if not base or manifest["initial_head"] != base or manifest["initial_status"]:
            raise PatchExportError("BASE_DIVERGENCE", "invalid recorded pristine base")
        if output(repo, "rev-parse", f"{base}^{{tree}}") != manifest["base_tree"]:
            raise PatchExportError("BASE_DIVERGENCE", "recorded base ref/tree lost")
        head = output(repo, "rev-parse", "HEAD")
        if git(repo, "merge-base", "--is-ancestor", base, head, check=False).returncode != 0:
            raise PatchExportError("BASE_DIVERGENCE", "HEAD left allowed base lineage")
        if manifest["expected_repo"]["kind"] == "git":
            expected_url = f"https://github.com/{manifest['expected_repo']['repo']}.git"
            if output(repo, "remote", "get-url", "origin") != expected_url:
                raise PatchExportError("BASE_DIVERGENCE", "source repository remote changed")
        status = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout.decode(errors="replace")
        unstaged = git(repo, "diff", "--binary").stdout
        staged = git(repo, "diff", "--cached", "--binary").stdout
        untracked = _paths(git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout)
        for name in untracked:
            candidate = repo / name
            if candidate.is_dir() and (candidate / ".git").exists():
                raise PatchExportError("PATCH_EXPORT_INVALID", f"nested repository: {name}")
        with tempfile.TemporaryDirectory(prefix="benchmark-index-") as temporary:
            index_path = str(Path(temporary) / "index")
            env = {**os.environ, "GIT_INDEX_FILE": index_path}
            git(repo, "read-tree", head, env=env)
            git(repo, "add", "-A", "--", ".", env=env)
            tree = output(repo, "write-tree", env=env)
        changed = _paths(git(repo, "diff", "--name-only", "-z", base, tree).stdout)
        tracked = _paths(git(repo, "ls-tree", "-r", "--name-only", "-z", base).stdout)
        if any(p.startswith(("benchmark-control/", ".git/", ".codegraph/")) or p == ".gitmodules" for p in changed):
            raise PatchExportError("PATCH_EXPORT_INVALID", "control plane or repository metadata touched")
        if len(changed) >= 20 and len(changed) >= int(0.8 * max(len(tracked), 1)):
            raise PatchExportError("PATCH_EXPORT_INVALID", "whole-repository change detected")
        raw = git(repo, "diff", "--raw", "-z", base, tree).stdout
        if b"160000" in raw:
            raise PatchExportError("PATCH_EXPORT_INVALID", "submodule/gitlink change detected")
        patch = git(repo, "diff", "--binary", "--full-index", "--no-ext-diff", base, tree).stdout
        if len(patch) > 30 * 1024 * 1024 and len(changed) >= 20:
            raise PatchExportError("PATCH_EXPORT_INVALID", "oversized multi-file patch requires review")
        patch_path.write_bytes(patch)
        result = {
            "status": "VALID", "task_id": task_id, "run_id": run_id,
            "base_sha": base, "base_tree": manifest["base_tree"],
            "head": head, "candidate_tree": tree, "repo_root": str(repo),
            "patch_path": str(patch_path), "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "patch_bytes": len(patch), "touched_paths": changed,
            "git_status": status, "unstaged_diff_bytes": len(unstaged),
            "staged_diff_bytes": len(staged), "untracked_paths": untracked,
        }
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        return patch_path
    except PatchExportError as error:
        patch_path.unlink(missing_ok=True)
        result_path.write_text(json.dumps({
            "status": error.status, "task_id": task_id,
            "run_id": run_id, "reason": str(error),
        }, indent=2) + "\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(export_patch(args.task, args.run_id))
