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
    "HERMES_RUNTIME_PATCH_MANIFEST.json",
    "SKILL_COPY_OWNERSHIP_MANIFEST.json",
    "SUT_SMOKE_EVIDENCE.json",
)
HARNESS_FILES = (
    "scripts/candidate_artifact.py",
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


def _git_bytes(runtime, *args):
    result = subprocess.run(["git", "-C", str(runtime), *args], capture_output=True)
    if result.returncode:
        raise FreezeError(f"SUT_GIT_COMMAND_FAILED: {' '.join(args)}")
    return result.stdout


def _skill_tree_sha256(root):
    """Hash non-hidden profile Skill content, excluding mutable usage/cache records."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise FreezeError(f"SUT_PROFILE_SKILL_SYMLINK: {relative}")
        if path.is_file():
            digest.update(relative.as_posix().encode() + b"\0")
            digest.update(format(path.stat().st_mode & 0o777, "04o").encode() + b"\0")
            digest.update(sha256(path).encode() + b"\n")
    return digest.hexdigest()


def verify_local_patch_set(runtime, manifest_path):
    """Accept only the exact declared tracked diff and untracked file set."""
    runtime = Path(runtime).resolve()
    manifest = json.loads(Path(manifest_path).read_text())
    head = _git_bytes(runtime, "rev-parse", "HEAD").decode().strip()
    upstream = manifest.get("upstream_sha")
    if (manifest.get("schema_version") != 1 or
            manifest.get("head_sha") != head or
            not upstream or
            _git_bytes(runtime, "merge-base", upstream, head).decode().strip() != upstream):
        raise FreezeError("SUT_PATCH_MANIFEST_IDENTITY_MISMATCH")
    if (hashlib.sha256(_git_bytes(runtime, "diff", "--binary", "HEAD")).hexdigest()
            != manifest.get("tracked_diff_sha256") or
            hashlib.sha256(_git_bytes(runtime, "diff", "--cached", "--binary", "HEAD")).hexdigest()
            != manifest.get("staged_diff_sha256")):
        raise FreezeError("SUT_TRACKED_PATCH_DRIFT")
    tracked_paths = {p.decode("utf-8", "surrogateescape") for p in
                     _git_bytes(runtime, "diff", "--name-only", "-z", "HEAD").split(b"\0") if p}
    tracked_entries = manifest.get("tracked_files", [])
    untracked_entries = manifest.get("untracked_files", [])
    declared_tracked = {entry["path"] for entry in tracked_entries}
    if tracked_paths != declared_tracked:
        raise FreezeError("SUT_TRACKED_PATH_DRIFT")
    untracked_paths = {p.decode("utf-8", "surrogateescape") for p in
                       _git_bytes(runtime, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p}
    declared_untracked = {entry["path"] for entry in untracked_entries}
    if untracked_paths != declared_untracked:
        raise FreezeError("SUT_UNDECLARED_DIRT")
    if (len(declared_tracked) != len(tracked_entries) or
            len(declared_untracked) != len(untracked_entries) or
            declared_tracked & declared_untracked):
        raise FreezeError("SUT_PATCH_MANIFEST_DUPLICATE_PATH")
    owner_path = Path(manifest_path).parent / manifest.get("skill_ownership_manifest", "")
    owners = json.loads(owner_path.read_text()) if manifest.get("skill_ownership_manifest") else None
    owner_files = {item["RUNTIME_PATH"]: item for item in owners["files"]} if owners else {}
    skill_paths = {item["path"] for item in untracked_entries
                   if item.get("classification") == "CANONICAL_RUNTIME_DEPENDENCY"}
    if skill_paths:
        if not owners:
            raise FreezeError("SUT_SKILL_OWNERSHIP_MISSING")
        profile_root = Path(owners["canonical_profile_root"]).resolve()
        if (owners.get("runtime_repo") != str(runtime) or
                len(owner_files) != len(owners["files"]) or
                set(owner_files) != skill_paths or
                owners.get("redundant_copies_removed") != 0 or
                owners.get("files_remaining_unknown") != 0 or
                _skill_tree_sha256(profile_root) != owners.get("profile_skill_tree_sha256")):
            raise FreezeError("SUT_SKILL_OWNERSHIP_DRIFT")
    unaccepted = []
    for entry in tracked_entries + untracked_entries:
        path = runtime / entry["path"]
        if (entry.get("classification") not in {"EXPECTED_LOCAL_PATCH", "RUNTIME_GENERATED_ARTIFACT",
                                                "CANONICAL_RUNTIME_DEPENDENCY", "ACCIDENTAL_DIRTY_STATE", "UNKNOWN"} or
                not entry.get("provenance") or not path.is_file() or path.is_symlink() or
                not path.resolve().is_relative_to(runtime) or sha256(path) != entry.get("sha256") or
                format(path.stat().st_mode & 0o777, "04o") != entry.get("mode")):
            raise FreezeError(f"SUT_DECLARED_PATCH_INVALID: {entry.get('path')}")
        if entry["classification"] == "CANONICAL_RUNTIME_DEPENDENCY":
            owner = owner_files[entry["path"]]
            if not entry["path"].startswith("skills/"):
                raise FreezeError(f"SUT_SKILL_OWNERSHIP_DRIFT: {entry['path']}")
            profile_path = profile_root / Path(entry["path"]).relative_to("skills")
            if (owner.get("CLASSIFICATION") != "CANONICAL_RUNTIME_DEPENDENCY" or
                    owner.get("CANONICAL_PROFILE_PATH") != str(profile_path) or
                    owner.get("SHA256_RUNTIME") != entry["sha256"] or
                    owner.get("SHA256_CANONICAL") != entry["sha256"] or
                    owner.get("BYTE_IDENTICAL") is not True or
                    owner.get("REFERENCED_BY_RUNTIME_CODE") is not True or
                    owner.get("SAFE_TO_REMOVE_FROM_RUNTIME_REPO") is not False or
                    not profile_path.resolve().is_relative_to(profile_root) or
                    not profile_path.is_file() or sha256(profile_path) != entry["sha256"]):
                raise FreezeError(f"SUT_SKILL_OWNERSHIP_DRIFT: {entry['path']}")
        if entry["classification"] in {"ACCIDENTAL_DIRTY_STATE", "UNKNOWN"}:
            unaccepted.append(entry["path"])
    if unaccepted:
        raise FreezeError(f"SUT_PATCH_UNACCEPTED: {len(unaccepted)} files, first={unaccepted[0]}")
    provenance = manifest.get("accepted_provenance")
    required = ("PURPOSE", "BASE_SHA", "DIFF_SHA256", "AFFECTED_FILE",
                "WHY_REQUIRED", "RUNTIME_EFFECT", "VERIFICATION_EVIDENCE")
    if (manifest.get("acceptance") != "ACCEPTED_FOR_CALIBRATION" or
            not isinstance(provenance, dict) or
            any(not provenance.get(key) for key in required) or
            provenance["BASE_SHA"] != upstream or
            provenance["DIFF_SHA256"] != manifest["tracked_diff_sha256"] or
            provenance["AFFECTED_FILE"] not in declared_tracked):
        raise FreezeError("SUT_PATCH_NOT_ACCEPTED")
    return {"status": "PASS", "head_sha": manifest["head_sha"],
            "tracked_files": len(tracked_paths), "untracked_files": len(untracked_paths)}


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
        if spec.get("local_patch_manifest"):
            verify_local_patch_set(spec["path"], repo / spec["local_patch_manifest"])
        elif command(["git", "-C", spec["path"], "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo):
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
