#!/usr/bin/env python3
"""Re-evaluate a candidate in a newly created official sandbox/job."""

import argparse
import json
import sys
from datetime import datetime, timezone

from grade_with_official_verifier import REPO_DIR, _task, grade_task

if __package__:
    from scripts.candidate_artifact import (CANDIDATE_ARTIFACT_TYPE, artifact_type,
                                            expected_install_status)
else:
    from candidate_artifact import (CANDIDATE_ARTIFACT_TYPE, artifact_type,
                                    expected_install_status)


def _artifact_type(task, grader):
    """The artifact type this evidence describes, or None when the record disagrees.

    The manifest track is authoritative and the recorded type must agree with it;
    a disagreement means nothing can be shown to have been installed, so the
    status is withheld rather than assumed. Partial task dicts without a track
    keep the git-patch semantics these field names are inherited from.
    """
    track = task.get("track")
    declared = grader.get("candidate_artifact_type")
    if track in CANDIDATE_ARTIFACT_TYPE:
        artifact = artifact_type(track)
        return artifact if declared in (None, artifact) else None
    if declared is not None:
        return declared if declared in CANDIDATE_ARTIFACT_TYPE else None
    return "GIT_PATCH"


def build_fresh_result(task_id, task, patch_sha256, grader):
    artifact = _artifact_type(task, grader)
    installed = (artifact is not None
                 and grader.get("patch_apply_status") == expected_install_status(artifact))
    status = grader.get("status", "INFRA_FAIL")
    return {
        "task_id": task_id,
        "status": status,
        "base_identity": grader.get("base_identity") or task.get("base_commit")
                         or task.get("container_image") or task.get("upstream_sha"),
        "candidate_artifact_type": artifact,
        "candidate_patch_sha256": patch_sha256,
        "sandbox_identity": grader.get("sandbox_identity"),
        "sandbox_identity_kind": grader.get("sandbox_identity_kind"),
        "patch_apply_status": grader.get("patch_apply_status", "UNKNOWN"),
        "candidate_installed": installed,
        "patch_applied": installed if artifact == "GIT_PATCH" else None,
        "official_grader_executed": grader.get("official_grader_executed") is True,
        "grader_exit_code": grader.get("grader_exit_code"),
        "grader_duration_ms": grader.get("grader_duration_ms"),
        "resolved": grader.get("resolved") if installed and status in ("PASS", "FAIL") else None,
        "raw_result_path": grader.get("raw_result_path"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def fresh_regrade(task_id, run_id):
    # grade_task uses a unique official run/job ID for every call. The pinned
    # evaluators create a fresh instance container and record its identity.
    task_dir = REPO_DIR / "runs" / run_id / "tasks" / task_id
    path = task_dir / "fresh-regrade-result.json"
    if path.exists():
        raise ValueError("existing fresh regrade evidence is immutable")
    first = json.loads((task_dir / "grader-result.json").read_text())
    if (first.get("status") not in ("PASS", "FAIL") or
            first.get("official_grader_executed") is not True or
            not first.get("sandbox_identity") or
            not first.get("candidate_patch_sha256")):
        raise ValueError("first official grader evidence is incomplete")
    grader = grade_task(task_id, run_id, phase="fresh-sandbox")
    task = _task(task_id)
    result = build_fresh_result(task_id, task, grader.get("candidate_patch_sha256"), grader)
    if (result["candidate_patch_sha256"] != first["candidate_patch_sha256"] or
            result["sandbox_identity"] == first["sandbox_identity"] or
            result["sandbox_identity"] is None):
        result.update(status="INVALID", resolved=None,
                      error="candidate patch or sandbox identity was not independent")
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = fresh_regrade(args.task, args.run_id)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] in ("PASS", "FAIL") else 1)
