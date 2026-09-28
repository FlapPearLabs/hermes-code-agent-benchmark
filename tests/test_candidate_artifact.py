"""Terminal candidate checks use recorded main and sidecar state."""

import json

import pytest

from scripts.candidate_artifact import (artifact_type, check_terminal_artifact_preflight,
                                        parse_terminal_reward_preflight)


def trial_fixture(tmp_path, reward):
    task = tmp_path / "payments-pipeline-fix"
    task.mkdir()
    (task / "task.toml").write_text('''
artifacts = ["/app/src/", { source = "/tmp/kafka-snapshot.tgz", service = "kafka" }]
[task]
name = "terminal-bench/payments-pipeline-fix"
[verifier]
environment_mode = "separate"
''')
    trial = tmp_path / "trial"
    for name in ("agent/hermes-stream.jsonl", "artifacts/app/src/code.py",
                 "artifacts/tmp/kafka-snapshot.tgz", "verifier/reward.txt"):
        (trial / name).parent.mkdir(parents=True, exist_ok=True)
    (trial / "agent/hermes-stream.jsonl").write_text('{"type":"init"}\n')
    (trial / "artifacts/app/src/code.py").write_text("candidate\n")
    (trial / "artifacts/tmp/kafka-snapshot.tgz").write_bytes(b"snapshot")
    (trial / "verifier/reward.txt").write_text(f"{reward}\n")
    (trial / "config.json").write_text("{}")
    (trial / "lock.json").write_text("{}")
    (trial / "result.json").write_text(json.dumps({
        "id": "trial-uuid", "task_name": "terminal-bench/payments-pipeline-fix",
        "exception_info": None, "verifier_result": {"rewards": {"reward": reward}},
    }))
    (trial / "artifacts/manifest.json").write_text(json.dumps([
        {"source": "/logs/artifacts", "destination": "artifacts/logs/artifacts", "type": "directory",
         "status": "empty", "service": None, "exclude": []},
        {"source": "/app/src/", "destination": "artifacts/app/src", "type": "directory",
         "status": "ok", "service": None, "exclude": []},
        {"source": "/tmp/kafka-snapshot.tgz", "destination": "artifacts/tmp/kafka-snapshot.tgz",
         "type": "file", "status": "ok", "service": "kafka", "exclude": []},
    ]))
    return task, trial


def test_candidate_types_reject_mismatch():
    assert artifact_type("swe-bench-verified") == "GIT_PATCH"
    assert artifact_type("swe-bench-pro-v2") == "GIT_PATCH"
    assert artifact_type("terminal-bench") == "SANDBOX_STATE"
    with pytest.raises(ValueError, match="CANDIDATE_ARTIFACT_TYPE_MISMATCH"):
        artifact_type("terminal-bench", "GIT_PATCH")


@pytest.mark.parametrize("reward,expected", [(1, "PASS"), (0, "FAIL")])
def test_stateful_official_verdict_is_distinct_from_infra_validity(tmp_path, reward, expected):
    task, trial = trial_fixture(tmp_path, reward)
    checked = check_terminal_artifact_preflight(task, trial, task.name)
    assert checked["declared_artifacts"] == 2
    assert checked["source_trial_authenticity"] == "NOT_PROVEN"
    verdict = parse_terminal_reward_preflight(trial, task.name, 0)
    assert verdict["status"] == expected
    assert verdict["resolved"] is (reward == 1)
    assert verdict["official_grader_process_proven"] is False


def test_missing_or_failed_sidecar_blocks_state_candidate(tmp_path):
    task, trial = trial_fixture(tmp_path, 0)
    (trial / "artifacts/tmp/kafka-snapshot.tgz").unlink()
    with pytest.raises(ValueError, match="TERMINAL_ARTIFACT_MISSING_OR_FAILED"):
        check_terminal_artifact_preflight(task, trial, task.name)
    (trial / "artifacts/tmp/kafka-snapshot.tgz").write_bytes(b"snapshot")
    manifest = json.loads((trial / "artifacts/manifest.json").read_text())
    manifest[2]["status"] = "failed"
    (trial / "artifacts/manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="TERMINAL_ARTIFACT_MISSING_OR_FAILED"):
        check_terminal_artifact_preflight(task, trial, task.name)


def test_manifest_cannot_redirect_a_declared_artifact(tmp_path):
    task, trial = trial_fixture(tmp_path, 1)
    manifest_path = trial / "artifacts/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[2]["destination"] = "artifacts/app/src/code.py"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="TERMINAL_ARTIFACT_MISSING_OR_FAILED"):
        check_terminal_artifact_preflight(task, trial, task.name)


def test_recorded_empty_directory_and_last_collection_match_harbor(tmp_path):
    task, trial = trial_fixture(tmp_path, 0)
    (trial / "artifacts/app/src/code.py").unlink()
    manifest_path = trial / "artifacts/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[1]["status"] = "failed"
    manifest.append({**manifest[1], "status": "empty"})
    manifest_path.write_text(json.dumps(manifest))
    assert check_terminal_artifact_preflight(task, trial, task.name)["source_trial_authenticity"] == "NOT_PROVEN"


def test_unsupported_fresh_replay_reported(tmp_path):
    task, trial = trial_fixture(tmp_path, 0)
    config = (task / "task.toml").read_text().replace('environment_mode = "separate"',
                                                      'environment_mode = "shared"')
    (task / "task.toml").write_text(config)
    with pytest.raises(ValueError, match="TERMINAL_FRESH_REPLAY_UNSUPPORTED"):
        check_terminal_artifact_preflight(task, trial, task.name)


def test_verifier_crash_cannot_be_a_task_fail(tmp_path):
    task, trial = trial_fixture(tmp_path, 0)
    with pytest.raises(ValueError, match="TERMINAL_OFFICIAL_VERIFIER_EVIDENCE_INVALID"):
        parse_terminal_reward_preflight(trial, task.name, 17)
