"""Terminal-Bench state replay adapter tests.

Covers the evidence the protocol requires:

A. without an authentic recorded trial the path fails closed and never starts
   the official grader process;
B. with one, the recorded sandbox state can be replayed and graded;
C. the SUT identity is carried through unchanged;
D. the official harness never becomes the SUT (no agent phase, stream copied);
E. gold is never read;
F. every replay builds an independent environment.
"""

import asyncio
import hashlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import terminal_replay as tr
import grade_with_official_verifier as grader
from candidate_artifact import check_terminal_artifact_preflight

TASK_ID = "payments-pipeline-fix"
TASK_NAME = f"terminal-bench/{TASK_ID}"
STREAM = b'{"type":"assistant","message":"recorded"}\n'
KAFKA_SNAPSHOT = b"\x1f\x8b\x08\x00recorded-kafka-log-snapshot"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

TASK_TOML = """
schema_version = "1.2"

artifacts = [
    "/app/src/",
    {{ source = "/tmp/kafka-snapshot.tgz", service = "kafka" }},
]

[task]
name = "{task_name}"

[verifier]
timeout_sec = 600.0
environment_mode = "separate"

[[verifier.collect]]
service = "kafka"
command = "tar czf /tmp/kafka-snapshot.tgz -C /tmp/kafka-logs ."
timeout_sec = 120.0

[agent]
timeout_sec = 28800.0
""".format(task_name=TASK_NAME)


def write_task(upstream, task_id=TASK_ID, *, toml=TASK_TOML):
    task_dir = Path(upstream) / "terminal-bench" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.toml").write_text(toml)
    # Present but must never be read by the adapter (gold isolation).
    (task_dir / "solution").mkdir(exist_ok=True)
    (task_dir / "solution" / "solve.sh").write_text("# gold patch\nexit 0\n")
    (task_dir / "tests").mkdir(exist_ok=True)
    (task_dir / "tests" / "test.sh").write_text("echo 1 > /logs/verifier/reward.txt\n")
    return task_dir


def artifact_manifest():
    return [
        {"source": "/logs/artifacts", "service": "main",
         "destination": "artifacts/logs/artifacts", "type": "directory",
         "status": "ok", "exclude": []},
        {"source": "/app/src/", "service": "main",
         "destination": "artifacts/app/src", "type": "directory",
         "status": "ok", "exclude": []},
        {"source": "/tmp/kafka-snapshot.tgz", "service": "kafka",
         "destination": "artifacts/tmp/kafka-snapshot.tgz", "type": "file",
         "status": "ok"},
    ]


def write_source_trial(root, task_dir, *, trial_id, name="source-trial",
                       reward="1", stream=STREAM):
    """A recorded candidate trial as Harbor writes it."""
    trial = Path(root) / name
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    (trial / "artifacts" / "logs" / "artifacts").mkdir(parents=True)
    (trial / "artifacts" / "app" / "src" / "worker").mkdir(parents=True)
    (trial / "artifacts" / "tmp").mkdir(parents=True)
    (trial / "agent" / "hermes-stream.jsonl").write_bytes(stream)
    (trial / "agent" / "hermes-stderr.log").write_text("")
    (trial / "agent" / "hermes-process.json").write_text(json.dumps(
        {"exit_code": 0, "timed_out": False, "duration_ms": 1200,
         "container": "proj-main-1", "argv": ["hermes"], "cwd": "/ws"}))
    (trial / "artifacts" / "manifest.json").write_text(
        json.dumps(artifact_manifest()))
    (trial / "artifacts" / "app" / "src" / "worker" / "main.py").write_text(
        "print('candidate state')\n")
    (trial / "artifacts" / "tmp" / "kafka-snapshot.tgz").write_bytes(KAFKA_SNAPSHOT)
    (trial / "verifier" / "reward.txt").write_text(reward)
    (trial / "lock.json").write_text('{"resolved": true}')
    (trial / "config.json").write_text(json.dumps(
        {"task": {"name": TASK_NAME, "path": str(task_dir)},
         "artifacts": ["/app/src/",
                       {"source": "/tmp/kafka-snapshot.tgz", "service": "kafka"}]}))
    (trial / "result.json").write_text(json.dumps(
        {"id": trial_id, "task_name": TASK_NAME, "trial_name": name,
         "agent_info": {"name": tr.SUT_AGENT_NAME, "version": tr.SUT_AGENT_VERSION,
                        "model_info": {"name": tr.SUT_MODEL_LABEL}},
         "verifier_result": {"rewards": {"reward": int(reward)}},
         "exception_info": None}))
    return trial


def write_regrade_trial(root, source_trial, *, trial_id, name="grade-grader-1",
                        reward="1", stream=None, action="regrade",
                        mode="separate", agent_execution=None, agent_info=None,
                        source_path=None):
    """A replay trial as ``harbor trials regrade`` writes it."""
    trial = Path(root) / name
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    (trial / "agent" / "hermes-stream.jsonl").write_bytes(
        STREAM if stream is None else stream)
    (trial / "verifier" / "reward.txt").write_text(reward)
    (trial / "result.json").write_text(json.dumps(
        {"id": trial_id, "task_name": TASK_NAME, "trial_name": name,
         "verifier_environment_mode": mode,
         "agent_execution": agent_execution,
         "agent_info": agent_info if agent_info is not None else {
             "name": tr.SUT_AGENT_NAME, "version": tr.SUT_AGENT_VERSION,
             "model_info": {"name": tr.SUT_MODEL_LABEL}},
         "verifier_result": {"rewards": {"reward": int(reward)}},
         "exception_info": None,
         "config": {"source_trial": {
             "action": action, "type": "local", "trial_id": "source-id",
             "path": str(source_path if source_path is not None
                         else source_trial.resolve())}}}))
    return trial


@pytest.fixture
def layout(tmp_path):
    """(upstream, repo, task_dir, source_trial) with the source outside a run."""
    upstream = tmp_path / "upstream"
    repo = tmp_path / "repo"
    repo.mkdir()
    task_dir = write_task(upstream)
    source = write_source_trial(tmp_path / "job", task_dir, trial_id="source-id")
    return upstream, repo, task_dir, source


def stream_sha():
    return hashlib.sha256(STREAM).hexdigest()


# ---------------------------------------------------------------------------
# command construction
# ---------------------------------------------------------------------------

def test_candidate_command_uses_the_pinned_sut_agent_and_kwargs():
    command = tr.candidate_trial_command(
        pinned_task_dir=Path("/tasks/t"), sut_workspace=Path("/ws"),
        sut_task_dir=Path("/td"), sut_timeout_sec=900, job_name="job",
        jobs_dir=Path("/jobs"), harbor_bin="/bin/harbor")
    assert command[:2] == ["/bin/harbor", "run"]
    assert command[command.index("-p") + 1] == "/tasks/t"
    assert command[command.index("-e") + 1] == "docker"
    assert command[command.index("-a") + 1] == tr.SUT_AGENT_IMPORT_PATH
    assert command[command.index("-m") + 1] == tr.SUT_MODEL_LABEL
    assert [command[i + 1] for i, item in enumerate(command) if item == "--ak"] == [
        "sut_workspace=/ws", "sut_task_dir=/td", "sut_timeout_sec=900"]
    assert command[command.index("--job-name") + 1] == "job"
    assert command[command.index("--jobs-dir") + 1] == "/jobs"


def test_regrade_command_is_the_official_trials_regrade_path():
    command = tr.regrade_command(
        source_trial=Path("/run/candidate"), official_task=Path("/tasks/t"),
        trial_name="grade-grader-abc", trials_dir=Path("/run/official"),
        harbor_bin="/bin/harbor")
    assert command[:4] == ["/bin/harbor", "trials", "regrade", "/run/candidate"]
    assert command[command.index("-p") + 1] == "/tasks/t"
    assert command[command.index("-e") + 1] == "docker"
    assert command[command.index("--trial-name") + 1] == "grade-grader-abc"
    assert command[command.index("-o") + 1] == "/run/official"


def test_prompt_does_not_leak_benchmark_knowledge():
    prompt = tr.build_terminal_prompt("Fix the pipeline.")
    assert prompt.startswith("Fix the pipeline.")
    assert "./bin/cmain" in prompt
    for leak in ("solution", "test.sh", "task.toml", "gold"):
        assert leak not in prompt


# ---------------------------------------------------------------------------
# trial location and state identity
# ---------------------------------------------------------------------------

def test_locate_trial_ignores_the_job_level_result_and_needs_one_match(tmp_path):
    job = tmp_path / "job"
    (job / "trial-a").mkdir(parents=True)
    (job / "trial-b").mkdir(parents=True)
    (job / "result.json").write_text(json.dumps({"task_name": TASK_NAME}))
    (job / "trial-a" / "result.json").write_text(json.dumps({"task_name": TASK_NAME}))
    assert tr.locate_trial(job, TASK_ID) == job / "trial-a"

    (job / "trial-b" / "result.json").write_text(json.dumps({"task_name": TASK_NAME}))
    with pytest.raises(RuntimeError, match="TERMINAL_TRIAL_UNRESOLVED"):
        tr.locate_trial(job, TASK_ID)


def test_locate_trial_rejects_a_job_that_ran_another_task(tmp_path):
    job = tmp_path / "job"
    (job / "trial-a").mkdir(parents=True)
    (job / "trial-a" / "result.json").write_text(
        json.dumps({"task_name": "terminal-bench/other-task"}))
    with pytest.raises(RuntimeError, match="matched=0"):
        tr.locate_trial(job, TASK_ID)


def test_candidate_state_sha256_is_content_identity(layout):
    _, _, _, source = layout
    first = tr.candidate_state_sha256(source)
    assert first == tr.candidate_state_sha256(source)
    (source / "artifacts" / "app" / "src" / "worker" / "main.py").write_text(
        "print('mutated')\n")
    assert tr.candidate_state_sha256(source) != first


# ---------------------------------------------------------------------------
# A. fail closed without an authentic recorded trial
# ---------------------------------------------------------------------------

def test_an_absent_source_trial_never_passes_the_artifact_gate(layout):
    _, _, task_dir, _ = layout
    # A missing record is a hard error, never a silent "nothing to check".
    with pytest.raises((ValueError, OSError)):
        check_terminal_artifact_preflight(task_dir, Path("/nope"), TASK_ID)


def test_a_source_trial_missing_its_collected_state_never_passes(layout):
    _, _, task_dir, source = layout
    (source / "artifacts" / "tmp" / "kafka-snapshot.tgz").unlink()
    with pytest.raises(ValueError):
        check_terminal_artifact_preflight(task_dir, source, TASK_ID)


def test_grade_terminal_without_a_recorded_trial_never_starts_the_grader(
        layout, monkeypatch):
    upstream, repo, _, _ = layout
    task_dir = write_task(upstream)
    task = {"task_id": TASK_ID, "track": "terminal-bench",
            "task_dir": str(task_dir), "upstream_sha": "deadbeef"}
    monkeypatch.setattr(grader, "REPO_DIR", repo)
    monkeypatch.setattr(grader, "UPSTREAM", upstream)
    started = []
    monkeypatch.setattr(grader, "_invoke",
                        lambda *a, **k: started.append(a) or (0, True, 1))
    outcome = grader._grade_terminal(TASK_ID, "run-x", "grader", task)
    assert outcome["status"] == "INVALID"
    assert outcome["official_grader_process_started"] is False
    assert outcome["official_grader_executed"] is False
    assert started == []


def test_grade_task_keeps_recording_invalid_evidence_for_an_unknown_task(
        tmp_path, monkeypatch):
    """An unusable task id must still land as INVALID evidence (the behaviour the
    git-patch path had before the terminal branch existed), not raise."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "benchmark-manifest.json").write_text(json.dumps(
        {"calibration_tasks": [], "scored_tasks": []}))
    monkeypatch.setattr(grader, "REPO_DIR", repo)
    outcome = grader.grade_task("no-such-task", "run-x", "grader")
    assert outcome["status"] == "INVALID"
    assert outcome["official_grader_executed"] is False
    assert (repo / "runs" / "run-x" / "tasks" / "no-such-task" / "grader-result.json").is_file()


# ---------------------------------------------------------------------------
# B. recorded state can be replayed and graded
# ---------------------------------------------------------------------------

def prepare_run(repo, task_dir, run_id="run-x"):
    """Materialise the run layout the grader expects; return (run_dir, source)."""
    run_dir = repo / "runs" / run_id / "tasks" / TASK_ID
    run_dir.mkdir(parents=True)
    (repo / "benchmark-manifest.json").write_text(json.dumps(
        {"calibration_tasks": [{"task_id": TASK_ID, "track": "terminal-bench",
                                "task_dir": str(task_dir),
                                "upstream_sha": "deadbeef"}],
         "scored_tasks": []}))
    source = write_source_trial(run_dir / "trials" / "candidate-job", task_dir,
                                trial_id="source-id")
    (run_dir / "trial-export-result.json").write_text(json.dumps(
        {"status": "VALID", "candidate_artifact_type": "SANDBOX_STATE",
         "candidate_trial_dir": str(source), "trial_id": "source-id"}))
    return run_dir, source


def wire_grader(monkeypatch, tmp_path, upstream, repo):
    monkeypatch.setattr(grader, "REPO_DIR", repo)
    monkeypatch.setattr(grader, "UPSTREAM", upstream)
    monkeypatch.setattr(grader, "HARBOR_ROOT", tmp_path / "harbor")
    monkeypatch.setattr(grader, "HARBOR_BIN", "/bin/harbor")
    monkeypatch.setattr(tr, "verify_harbor_pin", lambda *a, **k: {"pin_sha": "x"})
    return json.loads((repo / "benchmark-manifest.json").read_text())[
        "calibration_tasks"][0]


def test_grade_terminal_grades_recorded_state_in_a_new_environment(
        tmp_path, layout, monkeypatch):
    upstream, repo, task_dir, _ = layout
    _, source = prepare_run(repo, task_dir)
    task = wire_grader(monkeypatch, tmp_path, upstream, repo)
    seen = {}

    def fake_invoke(command, cwd, env, evidence_dir, prefix):
        seen["argv"] = command
        write_regrade_trial(Path(command[command.index("-o") + 1]), source,
                            trial_id="replay-id",
                            name=command[command.index("--trial-name") + 1])
        return 0, True, 7

    monkeypatch.setattr(grader, "_invoke", fake_invoke)
    outcome = grader._grade_terminal(TASK_ID, "run-x", "grader", task)

    assert seen["argv"][1:3] == ["trials", "regrade"]
    assert outcome["status"] == "PASS" and outcome["resolved"] is True
    assert outcome["official_grader_executed"] is True
    assert outcome["official_grader_process_proven"] is True
    assert outcome["official_grader_agent"] == "nop"
    assert outcome["sandbox_identity"] == "replay-id"
    assert outcome["replay_agent_phase_executed"] is False
    assert outcome["candidate_patch_sha256"] == tr.candidate_state_sha256(source)
    assert Path(outcome["raw_result_path"]).is_file()
    assert Path(outcome["replay_trial_dir"]).is_dir()


def test_grade_terminal_reports_an_unfaithful_replay_as_invalid(
        tmp_path, layout, monkeypatch):
    upstream, repo, task_dir, _ = layout
    _, source = prepare_run(repo, task_dir)
    task = wire_grader(monkeypatch, tmp_path, upstream, repo)

    def fake_invoke(command, cwd, env, evidence_dir, prefix):
        write_regrade_trial(Path(command[command.index("-o") + 1]), source,
                            trial_id="source-id",
                            name=command[command.index("--trial-name") + 1])
        return 0, True, 7

    monkeypatch.setattr(grader, "_invoke", fake_invoke)
    outcome = grader._grade_terminal(TASK_ID, "run-x", "grader", task)
    assert outcome["status"] == "INVALID"
    assert "SANDBOX_NOT_INDEPENDENT" in outcome["error"]
    assert outcome["official_grader_executed"] is False


# ---------------------------------------------------------------------------
# C/D. SUT identity preserved; official harness never becomes the SUT
# ---------------------------------------------------------------------------

def _replay(layout, tmp_path, **kwargs):
    _, _, _, source = layout
    return write_regrade_trial(tmp_path / "replays", source, **kwargs)


def test_replay_evidence_accepts_a_clean_official_replay(layout, tmp_path):
    _, _, _, source = layout
    trial = _replay(layout, tmp_path, trial_id="replay-id")
    evidence = tr.read_replay_evidence(
        task_id=TASK_ID, trial_dir=trial, exit_code=0, source_trial_dir=source,
        source_trial_id="source-id", source_stream_sha256=stream_sha(),
        candidate_state_sha256_value=tr.candidate_state_sha256(source))
    assert evidence["status"] == "PASS"
    assert evidence["replay_sut_identity"] == tr.SUT_AGENT_NAME
    assert evidence["replay_agent_phase_executed"] is False
    assert evidence["official_grader_process_proven"] is True


def test_replay_evidence_rejects_a_trial_that_ran_an_agent_phase(layout, tmp_path):
    trial = _replay(layout, tmp_path, trial_id="replay-id",
                    agent_execution={"started_at": "2026-01-01T00:00:00Z",
                                     "finished_at": "2026-01-01T00:01:00Z"})
    with pytest.raises(ValueError, match="UNEXPECTED_AGENT_PHASE"):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


def test_replay_evidence_rejects_a_regenerated_sut_stream(layout, tmp_path):
    trial = _replay(layout, tmp_path, trial_id="replay-id", stream=b"regenerated\n")
    with pytest.raises(ValueError, match="SUT_STREAM_REGENERATED"):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


@pytest.mark.parametrize("agent_info", [
    {"name": "oracle", "version": tr.SUT_AGENT_VERSION,
     "model_info": {"name": tr.SUT_MODEL_LABEL}},
    {"name": tr.SUT_AGENT_NAME, "version": "9.9.9",
     "model_info": {"name": tr.SUT_MODEL_LABEL}},
    {"name": tr.SUT_AGENT_NAME, "version": tr.SUT_AGENT_VERSION,
     "model_info": {"name": "gpt-4"}},
])
def test_replay_evidence_rejects_a_changed_sut_identity(layout, tmp_path, agent_info):
    trial = _replay(layout, tmp_path, trial_id="replay-id", agent_info=agent_info)
    with pytest.raises(ValueError, match="SUT_IDENTITY_CHANGED"):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


# ---------------------------------------------------------------------------
# provenance of the replay itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs,match", [
    ({"action": "diff"}, "NOT_A_REGRADE"),
    ({"source_path": "/elsewhere"}, "NOT_A_REGRADE"),
    ({"mode": "shared"}, "NOT_SEPARATE_VERIFIER"),
])
def test_replay_evidence_requires_a_regrade_of_this_source(
        layout, tmp_path, kwargs, match):
    trial = _replay(layout, tmp_path, trial_id="replay-id", **kwargs)
    with pytest.raises(ValueError, match=match):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


def test_replay_evidence_rejects_inconsistent_reward_evidence(layout, tmp_path):
    trial = _replay(layout, tmp_path, trial_id="replay-id")
    (trial / "verifier" / "reward.txt").write_text("0")
    with pytest.raises(ValueError):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


def test_replay_evidence_propagates_a_failed_official_process(layout, tmp_path):
    trial = _replay(layout, tmp_path, trial_id="replay-id")
    with pytest.raises(ValueError):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=1,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


# ---------------------------------------------------------------------------
# F. every replay is an independent environment
# ---------------------------------------------------------------------------

def test_replay_evidence_rejects_reusing_the_source_environment(layout, tmp_path):
    trial = _replay(layout, tmp_path, trial_id="source-id")
    with pytest.raises(ValueError, match="SANDBOX_NOT_INDEPENDENT"):
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0,
            source_trial_dir=layout[3], source_trial_id="source-id",
            source_stream_sha256=stream_sha(), candidate_state_sha256_value="x")


def test_two_replays_of_one_record_land_in_two_environments(layout, tmp_path):
    _, _, _, source = layout
    identities = []
    for root, trial_id in ((tmp_path / "a", "replay-1"), (tmp_path / "b", "replay-2")):
        trial = write_regrade_trial(root, source, trial_id=trial_id)
        identities.append(tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0, source_trial_dir=source,
            source_trial_id="source-id", source_stream_sha256=stream_sha(),
            candidate_state_sha256_value=tr.candidate_state_sha256(source))
            ["sandbox_identity"])
    assert identities == ["replay-1", "replay-2"]


# ---------------------------------------------------------------------------
# E. gold is never read
# ---------------------------------------------------------------------------

_AUDIT = {"installed": False, "enabled": False, "record": None}


def _ensure_audit_hook():
    """Install the ``open`` audit hook exactly once.

    CPython audit hooks cannot be removed, so recording is gated by an explicit
    ``enabled`` flag. Gating on the truthiness of the record list instead would
    silently disable the hook the moment the list is cleared — an empty list is
    falsy — and the gold assertion below would pass vacuously.
    """
    if _AUDIT["installed"]:
        return

    def hook(event, args):
        if event == "open" and _AUDIT["enabled"]:
            _AUDIT["record"].append(str(args[0]))

    sys.addaudithook(hook)
    _AUDIT["installed"] = True


class audit_opens:
    """Record every path opened inside the block."""

    def __enter__(self):
        _ensure_audit_hook()
        _AUDIT["record"] = opened = []
        _AUDIT["enabled"] = True
        return opened

    def __exit__(self, *exc_info):
        _AUDIT["enabled"] = False
        return False


def _gold_reads(seen, task_dir):
    return [p for p in seen
            if str(task_dir / "solution") in p or str(task_dir / "tests") in p]


def test_replay_evidence_reads_no_gold(layout, tmp_path):
    _, _, task_dir, source = layout
    trial = _replay(layout, tmp_path, trial_id="replay-id")
    with audit_opens() as seen:
        tr.read_replay_evidence(
            task_id=TASK_ID, trial_dir=trial, exit_code=0, source_trial_dir=source,
            source_trial_id="source-id", source_stream_sha256=stream_sha(),
            candidate_state_sha256_value=tr.candidate_state_sha256(source))
        assert seen, "audit hook captured nothing; the assertion would be vacuous"
    assert _gold_reads(seen, task_dir) == []


def test_grade_terminal_reads_no_gold(tmp_path, layout, monkeypatch):
    """The whole grading path — not just the evidence parser — must leave the
    task's gold untouched."""
    upstream, repo, task_dir, _ = layout
    _, source = prepare_run(repo, task_dir)
    task = wire_grader(monkeypatch, tmp_path, upstream, repo)

    def fake_invoke(command, cwd, env, evidence_dir, prefix):
        write_regrade_trial(Path(command[command.index("-o") + 1]), source,
                            trial_id="replay-id",
                            name=command[command.index("--trial-name") + 1])
        return 0, True, 1

    monkeypatch.setattr(grader, "_invoke", fake_invoke)
    with audit_opens() as seen:
        grader._grade_terminal(TASK_ID, "run-x", "grader", task)
        # Positive control: the hook must observe this path's real file traffic,
        # otherwise the gold check below proves nothing.
        assert any("trial-export-result.json" in p for p in seen), seen
    assert _gold_reads(seen, task_dir) == []


def test_verify_sandbox_really_denies_the_benchmark_control_plane(tmp_path):
    """End-to-end gold-isolation proof: a real sandboxed read of the benchmark
    control plane must fail while the task instruction stays readable."""
    import platform
    if platform.system() != "Darwin":
        pytest.skip("sandbox-exec is macOS only")
    from verify_agent_sandbox import prove_sandbox
    repo = tmp_path / "repo"
    workspace = repo / "agent-workspaces" / "run-x" / TASK_ID
    (workspace / "repo").mkdir(parents=True)
    (workspace / "PROBLEM.md").write_text("task instruction\n")
    (repo / "benchmark-manifest.json").write_text('{"calibration_tasks": []}')
    task_dir = tmp_path / "sandbox-proof"
    prefix = prove_sandbox(workspace, task_dir, repo)
    proof = json.loads((task_dir / "agent-sandbox-proof.json").read_text())
    assert proof["status"] == "PASS"
    assert proof["probes"]["task_instruction"]["exit_code"] == 0
    assert proof["probes"]["benchmark_control"]["exit_code"] != 0
    assert prefix[:2] == ["sandbox-exec", "-f"]


def test_sandbox_profile_denies_the_task_cache_and_benchmark_repo(tmp_path):
    from verify_agent_sandbox import profile_for, UPSTREAM_CACHE
    workspace = tmp_path / "repo" / "agent-workspaces" / "run-x" / TASK_ID
    (workspace / "repo").mkdir(parents=True)
    (workspace / "PROBLEM.md").write_text("task")
    profile = profile_for(workspace, tmp_path / "repo")
    assert "deny file-read*" in profile
    assert str(UPSTREAM_CACHE) in profile
    assert str((tmp_path / "repo").resolve()) in profile


# ---------------------------------------------------------------------------
# Harbor pin / provenance
# ---------------------------------------------------------------------------

class _Proc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


def test_verify_harbor_pin_checks_sha_tree_and_version(tmp_path, monkeypatch):
    root, binary = tmp_path / "harbor", tmp_path / "bin" / "harbor"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "rev-parse" in argv:
            return _Proc(0, tr.HARBOR_PIN_SHA + "\n")
        if "status" in argv:
            return _Proc(0, "")
        return _Proc(0, tr.HARBOR_PIN_VERSION + "\n")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    monkeypatch.setattr(tr, "harbor_runtime_identity", lambda root, b: {"runtime_path": "x"})
    assert tr.verify_harbor_pin(root, binary)["pin_sha"] == tr.HARBOR_PIN_SHA
    assert len(calls) == 3

    monkeypatch.setattr(
        tr.subprocess, "run",
        lambda argv, **k: _Proc(0, "0000\n") if "rev-parse" in argv
        else _Proc(0, ""))
    with pytest.raises(RuntimeError, match="HARBOR_PIN_MISMATCH"):
        tr.verify_harbor_pin(root, binary)

    monkeypatch.setattr(
        tr.subprocess, "run",
        lambda argv, **k: _Proc(0, tr.HARBOR_PIN_SHA + "\n")
        if "rev-parse" in argv else _Proc(0, " M dirty.py\n"))
    with pytest.raises(RuntimeError, match="HARBOR_TREE_DIRTY"):
        tr.verify_harbor_pin(root, binary)

    def version_run(argv, **kwargs):
        if "rev-parse" in argv:
            return _Proc(0, tr.HARBOR_PIN_SHA + "\n")
        if "status" in argv:
            return _Proc(0, "")
        return _Proc(0, "9.9.9\n")

    monkeypatch.setattr(tr.subprocess, "run", version_run)
    with pytest.raises(RuntimeError, match="HARBOR_VERSION_MISMATCH"):
        tr.verify_harbor_pin(root, binary)


def test_harbor_runtime_identity_requires_the_pinned_source_tree(tmp_path, monkeypatch):
    """The digest must describe the package that actually executes: both call
    sites prepend ``<harbor_root>/src`` to PYTHONPATH, so a resolution landing
    anywhere else is a hard error rather than a recorded curiosity."""
    root, binary = tmp_path / "harbor", tmp_path / "bin" / "harbor"
    (root / "src" / "harbor").mkdir(parents=True)
    (root / "src" / "harbor" / "__init__.py").write_text("")
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    seen = {}

    monkeypatch.setattr(tr, "_harbor_interpreter", lambda b: "/usr/bin/python3")

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env") or {}
        return _Proc(0, str(root / "src" / "harbor") + "\n")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    identity = tr.harbor_runtime_identity(root, binary)
    assert identity["runtime_path"] == str((root / "src" / "harbor").resolve())
    assert identity["runtime_digest"] == tr.tree_sha256(root / "src" / "harbor")
    # The probe must resolve harbor the same way the real callers do.
    assert (root / "src") .as_posix() in seen["env"]["PYTHONPATH"]

    monkeypatch.setattr(tr.subprocess, "run",
                        lambda argv, **k: _Proc(0, str(tmp_path / "site-packages" / "harbor")))
    with pytest.raises(RuntimeError, match="RESOLUTION_MISMATCH"):
        tr.harbor_runtime_identity(root, binary)

    monkeypatch.setattr(tr, "_harbor_interpreter", lambda b: None)
    with pytest.raises(RuntimeError, match="UNRESOLVED"):
        tr.harbor_runtime_identity(root, binary)


def test_tree_sha256_is_stable_and_ignores_caches(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.pyc").write_bytes(b"cache")
    digest = tr.tree_sha256(tmp_path)
    assert digest == tr.tree_sha256(tmp_path)
    (tmp_path / "a.txt").write_text("b")
    assert tr.tree_sha256(tmp_path) != digest


# ---------------------------------------------------------------------------
# candidate host bridge
# ---------------------------------------------------------------------------

def test_host_agent_records_a_complete_sut_trial(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    logs = tmp_path / "trial" / "agent"
    monkeypatch.setattr("verify_agent_sandbox.prove_sandbox",
                        lambda ws, td, repo: ["sandbox-exec", "-f", "profile"])
    monkeypatch.setattr(tr, "discover_main_container", lambda session: "proj-main-1")

    def fake_run(argv, **kwargs):
        kwargs["stdout"].write('{"type":"assistant"}\n')
        kwargs["stderr"].write("")
        return _Proc(0)

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    agent = tr.HermesCodeHostAgent(logs_dir=logs, sut_workspace=workspace,
                                   sut_task_dir=tmp_path / "taskdir",
                                   sut_timeout_sec=42)

    class Env:
        session_id = "trial__env"

    asyncio.run(agent.run("Fix the pipeline.", Env(), None))
    bridge = workspace / "bin" / "cmain"
    assert bridge.read_text() == '#!/bin/sh\nexec docker exec proj-main-1 "$@"\n'
    assert bridge.stat().st_mode & 0o111
    record = json.loads((logs / tr.REPLAY_PROCESS_RECORD).read_text())
    assert record["exit_code"] == 0 and record["container"] == "proj-main-1"
    assert tr.read_candidate_evidence(logs.parent, TASK_ID)["sut_stream_sha256"] == \
        hashlib.sha256(b'{"type":"assistant"}\n').hexdigest()


def test_host_agent_surfaces_a_failed_sut_run(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr("verify_agent_sandbox.prove_sandbox",
                        lambda ws, td, repo: ["sandbox-exec", "-f", "profile"])
    monkeypatch.setattr(tr, "discover_main_container", lambda session: "c")

    def fake_run(argv, **kwargs):
        kwargs["stdout"].write("")
        kwargs["stderr"].write("boom\n")
        return _Proc(3)

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    agent = tr.HermesCodeHostAgent(logs_dir=tmp_path / "agent",
                                   sut_workspace=workspace,
                                   sut_task_dir=tmp_path / "t", sut_timeout_sec=5)
    with pytest.raises(RuntimeError, match="HERMES_SUT_RUN_FAILED"):
        asyncio.run(agent.run("x", type("E", (), {"session_id": "s"})(), None))


def test_plugin_constructors_forward_base_kwargs_when_harbor_is_present(
        tmp_path, monkeypatch):
    """Regression: the Harbor base requires ``logs_dir``; the plugin must pass
    the keyword arguments through exactly once."""
    import importlib
    import types

    package = types.ModuleType("harbor")
    package.__path__ = []
    agents = types.ModuleType("harbor.agents")
    agents.__path__ = []
    base = types.ModuleType("harbor.agents.base")

    class FakeBaseAgent:
        def __init__(self, logs_dir, model_name=None, logger=None, **kwargs):
            self.logs_dir = Path(logs_dir)
            self.model_name = model_name
            self.extra = kwargs

        @classmethod
        def preflight(cls, **kwargs):
            return None

    base.BaseAgent = FakeBaseAgent
    for name, module in (("harbor", package), ("harbor.agents", agents),
                         ("harbor.agents.base", base)):
        monkeypatch.setitem(sys.modules, name, module)
    original = sys.modules.get("terminal_replay")
    monkeypatch.delitem(sys.modules, "terminal_replay", raising=False)
    try:
        module = importlib.import_module("terminal_replay")
        assert module.HARBOR_AVAILABLE is True
        agent = module.HermesCodeHostAgent(
            logs_dir=tmp_path / "agent", model_name="m", sut_workspace="/ws",
            sut_task_dir="/td", sut_timeout_sec=10)
        assert agent.logs_dir == tmp_path / "agent"
        assert agent.model_name == "m"
        with pytest.raises(ValueError, match="AGENT_KWARG_MISSING"):
            module.HermesCodeHostAgent(logs_dir=tmp_path / "a")
    finally:
        if original is not None:
            sys.modules["terminal_replay"] = original
        else:
            sys.modules.pop("terminal_replay", None)


def test_the_fixture_models_the_real_pinned_task_declarations():
    real = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check"
                "/terminal-bench/tasks") / TASK_ID / "task.toml"
    if not real.is_file():
        pytest.skip("pinned terminal-bench cache is absent")
    with real.open("rb") as handle:
        config = tomllib.load(handle)
    declared = json.loads(json.dumps(config["artifacts"]))
    assert config["task"]["name"] == TASK_NAME
    assert config["verifier"]["environment_mode"] == "separate"
    assert declared == ["/app/src/",
                        {"source": "/tmp/kafka-snapshot.tgz", "service": "kafka"}]
    collect = config["verifier"]["collect"][0]
    assert collect["service"] == "kafka"
    assert "-C /tmp/kafka-logs ." in collect["command"]
