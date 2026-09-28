"""Benchmark-native candidate types and Terminal trial artifact checks."""

import json
import tomllib
from pathlib import Path
from pathlib import PurePosixPath


CANDIDATE_ARTIFACT_TYPE = {
    "swe-bench-verified": "GIT_PATCH",
    "swe-bench-pro-v2": "GIT_PATCH",
    "terminal-bench": "SANDBOX_STATE",
}


def artifact_type(track, declared=None):
    expected = CANDIDATE_ARTIFACT_TYPE[track]
    if declared is not None and declared != expected:
        raise ValueError(f"CANDIDATE_ARTIFACT_TYPE_MISMATCH: {track}: {declared}")
    return expected


def check_terminal_artifact_preflight(task_dir, trial_dir, task_id):
    """Check recorded artifact shape; only pinned Harbor can authenticate/regrade a trial."""
    task_dir, trial_dir = Path(task_dir), Path(trial_dir)
    with (task_dir / "task.toml").open("rb") as source:
        config = tomllib.load(source)
    if config["verifier"]["environment_mode"] != "separate":
        raise ValueError("TERMINAL_FRESH_REPLAY_UNSUPPORTED")
    result = json.loads((trial_dir / "result.json").read_text())
    if result.get("task_name") != config["task"]["name"] or task_dir.name != task_id:
        raise ValueError("TERMINAL_SOURCE_TRIAL_IDENTITY_MISMATCH")
    for name in ("config.json", "lock.json", "agent/hermes-stream.jsonl",
                 "verifier/reward.txt"):
        if not (trial_dir / name).is_file() or (trial_dir / name).stat().st_size == 0:
            raise ValueError(f"TERMINAL_SOURCE_TRIAL_INCOMPLETE: {name}")
    entries = json.loads((trial_dir / "artifacts" / "manifest.json").read_text())
    if not isinstance(entries, list):
        raise ValueError("TERMINAL_ARTIFACT_MANIFEST_INVALID")
    trial_config = json.loads((trial_dir / "config.json").read_text())
    declared = [*config.get("artifacts", []), *trial_config.get("artifacts", [])]
    if not any((item if isinstance(item, str) else item["source"]).rstrip("/") == "/logs/artifacts"
               for item in declared):
        declared.insert(0, "/logs/artifacts")
    for item in declared:
        source = item if isinstance(item, str) else item["source"]
        service = None if isinstance(item, str) else item.get("service")
        destination = source if isinstance(item, str) else item.get("destination") or source
        expected_destination = "artifacts/" + "/".join(
            part for part in PurePosixPath(destination).parts if part not in ("/", "", ".."))
        expected_exclude = [] if isinstance(item, str) else item.get("exclude", [])
        matched = [entry for entry in entries if entry.get("source", "").rstrip("/") == source.rstrip("/")
                   and entry.get("service") in (service, "main" if service is None else service)
                   and entry.get("destination") == expected_destination]
        if not matched or matched[-1].get("status") not in ("ok", "empty"):
            raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
        entry = matched[-1]
        if entry.get("type") == "directory":
            if entry.get("exclude") is None and expected_exclude:
                raise ValueError(f"TERMINAL_ARTIFACT_FILTER_MISMATCH: {source}")
            if entry.get("exclude") is not None and set(entry["exclude"]) != set(expected_exclude):
                raise ValueError(f"TERMINAL_ARTIFACT_FILTER_MISMATCH: {source}")
        elif entry.get("type") != "file" or entry["status"] == "empty":
            raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
        if source.endswith("/") and entry.get("type") != "directory":
            raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
        if entry["status"] == "empty":
            if entry["type"] != "directory":
                raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
            continue
        target = (trial_dir / expected_destination).resolve()
        if not target.is_relative_to(trial_dir.resolve()) or not target.exists():
            raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
        if entry["type"] == "directory":
            if not target.is_dir():
                raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
        elif not target.is_file() or target.stat().st_size == 0:
            raise ValueError(f"TERMINAL_ARTIFACT_MISSING_OR_FAILED: {source}")
    if not result.get("id"):
        raise ValueError("TERMINAL_SOURCE_TRIAL_IDENTITY_MISMATCH")
    return {"candidate_artifact_type": "SANDBOX_STATE", "trial_id": result["id"],
            "declared_artifacts": len(declared) - 1, "source_trial_authenticity": "NOT_PROVEN"}


def parse_terminal_reward_preflight(trial_dir, task_id, exit_code):
    """Parse a recorded reward; process execution and trial independence need separate proof."""
    trial_dir = Path(trial_dir)
    raw = json.loads((trial_dir / "result.json").read_text())
    reward_text = (trial_dir / "verifier" / "reward.txt").read_text().strip()
    verifier = raw.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    if (exit_code != 0 or raw.get("task_name", "").split("/")[-1] != task_id or
            raw.get("exception_info") is not None or reward_text not in ("0", "1") or
            type(reward) not in (int, float) or reward != int(reward_text) or not raw.get("id")):
        raise ValueError("TERMINAL_OFFICIAL_VERIFIER_EVIDENCE_INVALID")
    return {"status": "PASS" if reward_text == "1" else "FAIL",
            "resolved": reward_text == "1", "trial_id": raw["id"],
            "official_grader_process_proven": False}
