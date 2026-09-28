"""Terminal-Bench state replay adapter — official Harbor source-trial bridge.

Terminal-Bench has no git patch to grade: a candidate is recorded *sandbox
state* (the mutated task tree plus the Kafka sidecar log snapshot). This module
supplies the two ends of that contract and nothing else:

* ``HermesCodeHostAgent`` (candidate phase) — Harbor owns the pinned task
  environment lifecycle only; the real, pinned host-side Hermes Code profile
  solves the task through a docker bridge and its stream is captured into the
  trial. Harbor then collects the task's declared artifacts, so the resulting
  trial is an authentic source trial.
* grading and fresh replay — Harbor's own ``trials regrade`` path. It seeds the
  recorded artifact bytes into a *fresh, separate verifier environment*, runs
  **no agent phase at all**, and re-runs the task's official verifier. Harbor
  itself rejects a record whose declared verifier inputs are missing, so a
  partial record can never be graded and nothing has to be re-derived here.

The checks that bound the record live in :mod:`candidate_artifact`; this module
adds only the Harbor-side command construction, the pin/provenance checks and
the replay-evidence parsing.

Importing this module without Harbor installed is supported (guarded base
class) so the runner, the grader and the test suite can use the pure helpers
anywhere; the Harbor plugin context always has Harbor on ``PYTHONPATH``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

if __package__:
    from scripts.candidate_artifact import (artifact_type, expected_install_status,
                                           parse_terminal_reward_preflight)
else:
    from candidate_artifact import (artifact_type, expected_install_status,
                                   parse_terminal_reward_preflight)

try:  # pragma: no cover - exercised only inside the Harbor plugin context
    from harbor.agents.base import BaseAgent as _HarborBaseAgent

    HARBOR_AVAILABLE = True
except Exception:  # pragma: no cover - plain host-side import (runner/grader/tests)
    HARBOR_AVAILABLE = False

    class _HarborBaseAgent:
        """Minimal stand-in so the plugin classes stay importable."""


HARBOR_PIN_SHA = "3c82380859d187957cfd5cd64802b076d9779550"
HARBOR_PIN_VERSION = "0.23.0"
TERMINAL_TRACK = "terminal-bench"
SANDBOX_STATE_ARTIFACT = artifact_type(TERMINAL_TRACK)
SANDBOX_STATE_INSTALL_STATUS = expected_install_status(SANDBOX_STATE_ARTIFACT)
SUT_AGENT_IMPORT_PATH = "terminal_replay:HermesCodeHostAgent"
SUT_AGENT_NAME = "hermes-code-host-agent"
SUT_AGENT_VERSION = "1.0.0"
SUT_MODEL_LABEL = "hermes-code-bot"
SUT_EXTRA_ENV = {"HERMES_YOLO_MODE": "1"}
REGRADE_ACTION = "regrade"
REGRADE_SOURCE_TYPE = "local"
REGRADE_TRIAL_PREFIX = "grade"
REPLAY_AGENT_STREAM = "hermes-stream.jsonl"
REPLAY_PROCESS_RECORD = "hermes-process.json"
_DIGEST_SKIP = ("__pycache__",)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Frozen SUT invocation contract (must match the SWE calibration runner)
# ---------------------------------------------------------------------------

def build_sut_command(prompt: str, sandbox_profile) -> list[str]:
    """The exact frozen Hermes Code harness invocation, sandboxed."""
    return [
        "sandbox-exec", "-f", str(sandbox_profile),
        "hermes", "-p", "code", "chat", "-q", prompt,
        "--yolo", "--max-turns", "60", "--format", "stream-json",
    ]


def build_terminal_prompt(instruction: str) -> str:
    """Official task instruction plus the container bridge contract.

    The contract adds no benchmark knowledge: it only states that the task
    environment lives in a docker container and that ``./bin/cmain`` is the
    wrapper the Code profile must use to reach it. It is deliberately
    independent of the container's concrete name so the same text can be
    frozen into the workspace's ``PROBLEM.md`` before Harbor starts.
    """
    return (
        f"{instruction}\n\n"
        "---\n"
        "ENVIRONMENT CONTRACT:\n"
        "- The task environment runs inside a docker container, not on this host.\n"
        "- Run every task command through `./bin/cmain <command...>`; it forwards "
        "the command into that container.\n"
        "- You may move files between this workspace and the container with "
        "`docker cp`.\n"
        "- Do not touch the host beyond this workspace.\n"
        "- Leave the required state inside the container, then exit cleanly."
    )


# ---------------------------------------------------------------------------
# Provenance: pinned Harbor source tree + the package that actually executes
# ---------------------------------------------------------------------------

def tree_sha256(root) -> str:
    """Deterministic content digest of a directory tree."""
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(p for p in root.rglob("*") if p.is_file()
                       and not any(part in _DIGEST_SKIP
                                   for part in p.relative_to(root).parts)):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return digest.hexdigest()


def _harbor_interpreter(harbor_bin):
    """The interpreter the harbor entry point runs under, when discoverable."""
    harbor_bin = Path(harbor_bin)
    try:
        shebang = harbor_bin.read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError):
        shebang = ""
    if shebang.startswith("#!"):
        candidate = Path(shebang[2:].strip().split()[0])
        if candidate.is_file():
            return candidate
    sibling = harbor_bin.parent / "python"
    return sibling if sibling.is_file() else None


def harbor_runtime_identity(harbor_root, harbor_bin, path_prefixes=()) -> dict:
    """Identity of the harbor package the official machinery will execute.

    Both call sites run harbor with ``<harbor_root>/src`` prepended to
    ``PYTHONPATH``, so that source tree — not the copy installed in the
    interpreter's site-packages — is what actually executes. The probe replays
    that same resolution and requires it to land on the pinned tree, so a pin
    that only matched a label while a different build ran could not pass.

    ``path_prefixes`` are the entries a caller places *ahead* of the pinned
    source tree; passing them makes the probe reproduce the resolution that
    caller will really get rather than only beating the ambient environment.
    """
    expected = (Path(harbor_root) / "src" / "harbor").resolve()
    interpreter = _harbor_interpreter(harbor_bin)
    if interpreter is None:
        raise RuntimeError("HARBOR_RUNTIME_UNRESOLVED: interpreter not discoverable")
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(
               (*(str(prefix) for prefix in path_prefixes),
                str(Path(harbor_root) / "src"),
                *(p for p in (os.environ.get("PYTHONPATH"),) if p)))}
    probe = subprocess.run(
        [str(interpreter), "-c",
         "import pathlib, harbor; print(pathlib.Path(harbor.__file__).resolve().parent)"],
        capture_output=True, text=True, env=env)
    if probe.returncode != 0:
        raise RuntimeError(
            f"HARBOR_RUNTIME_UNRESOLVED: {probe.stderr.strip()[-200:]}")
    resolved = Path(probe.stdout.strip()).resolve()
    if resolved != expected:
        raise RuntimeError(
            f"HARBOR_RUNTIME_RESOLUTION_MISMATCH: {resolved} != {expected}")
    return {"runtime_path": str(resolved), "runtime_digest": tree_sha256(resolved)}


def verify_harbor_pin(harbor_root, harbor_bin, path_prefixes=()) -> dict:
    """The official replay machinery must be the pinned Harbor release."""
    head = subprocess.run(["git", "-C", str(harbor_root), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if head.returncode != 0 or head.stdout.strip() != HARBOR_PIN_SHA:
        raise RuntimeError(f"HARBOR_PIN_MISMATCH: {harbor_root}")
    dirty = subprocess.run(["git", "-C", str(harbor_root), "status", "--porcelain"],
                           capture_output=True, text=True)
    if dirty.returncode != 0 or dirty.stdout.strip():
        raise RuntimeError(f"HARBOR_TREE_DIRTY: {harbor_root}")
    version = subprocess.run([str(harbor_bin), "--version"], capture_output=True, text=True)
    if version.returncode != 0 or version.stdout.strip() != HARBOR_PIN_VERSION:
        raise RuntimeError("HARBOR_VERSION_MISMATCH")
    return {"pin_sha": HARBOR_PIN_SHA, "version": HARBOR_PIN_VERSION,
            **harbor_runtime_identity(harbor_root, harbor_bin, path_prefixes)}


# ---------------------------------------------------------------------------
# Harbor job commands (pure; testable without Harbor/docker)
# ---------------------------------------------------------------------------

def candidate_trial_command(*, pinned_task_dir, sut_workspace, sut_task_dir,
                            sut_timeout_sec, job_name, jobs_dir,
                            harbor_bin="harbor") -> list[str]:
    """Produce an authentic source trial with the real pinned Code profile."""
    return [
        str(harbor_bin), "run",
        "-p", str(pinned_task_dir),
        "-e", "docker",
        "-a", SUT_AGENT_IMPORT_PATH,
        "-m", SUT_MODEL_LABEL,
        "--ak", f"sut_workspace={sut_workspace}",
        "--ak", f"sut_task_dir={sut_task_dir}",
        "--ak", f"sut_timeout_sec={sut_timeout_sec}",
        "--job-name", job_name,
        "--jobs-dir", str(jobs_dir),
    ]


def regrade_command(*, source_trial, official_task, trial_name, trials_dir,
                    harbor_bin="harbor") -> list[str]:
    """Official replay: recorded state -> fresh separate verifier environment."""
    return [
        str(harbor_bin), "trials", "regrade", str(source_trial),
        "-p", str(official_task),
        "-e", "docker",
        "--trial-name", trial_name,
        "-o", str(trials_dir),
    ]


# ---------------------------------------------------------------------------
# Candidate / replay trial identification and evidence
# ---------------------------------------------------------------------------

def _load_json(path) -> dict:
    return json.loads(Path(path).read_text())


def candidate_state_sha256(trial_dir) -> str:
    """Content identity of the recorded candidate state (collected artifacts)."""
    return tree_sha256(Path(trial_dir) / "artifacts")


def locate_trial(job_dir, task_id) -> Path:
    """The single trial directory under a job that ran *task_id*.

    Job directories carry their own ``result.json`` next to the trial
    directories, so only child directories are considered.
    """
    trials = []
    for result_path in sorted(Path(job_dir).glob("*/result.json")):
        try:
            raw = _load_json(result_path)
        except (OSError, ValueError):
            continue
        if str(raw.get("task_name", "")).split("/")[-1] == task_id:
            trials.append(result_path.parent)
    if len(trials) != 1:
        raise RuntimeError(
            f"TERMINAL_TRIAL_UNRESOLVED: task={task_id} matched={len(trials)}")
    return trials[0]


def read_candidate_evidence(trial_dir, task_id) -> dict:
    """Locate the SUT evidence a recorded source trial must carry."""
    trial_dir = Path(trial_dir)
    stream = trial_dir / "agent" / REPLAY_AGENT_STREAM
    process = trial_dir / "agent" / REPLAY_PROCESS_RECORD
    if not stream.is_file() or stream.stat().st_size == 0:
        raise ValueError("TERMINAL_SOURCE_TRIAL_INCOMPLETE: agent/hermes-stream.jsonl")
    if not process.is_file():
        raise ValueError("TERMINAL_SOURCE_TRIAL_INCOMPLETE: agent/hermes-process.json")
    record = _load_json(process)
    if record.get("exit_code") != 0 or record.get("timed_out"):
        raise ValueError(
            f"TERMINAL_SOURCE_TRIAL_INCOMPLETE: SUT exit={record.get('exit_code')} "
            f"timed_out={record.get('timed_out')}")
    stream_sha = hashlib.sha256(stream.read_bytes()).hexdigest()
    return {
        "sut_stream_path": str(stream),
        "sut_stream_sha256": stream_sha,
        "sut_container": record.get("container"),
        "sut_command": record.get("argv"),
        "sut_cwd": record.get("cwd"),
        "sut_duration_ms": record.get("duration_ms"),
    }


def read_replay_evidence(*, task_id, trial_dir, exit_code, source_trial_dir,
                         source_trial_id, source_stream_sha256,
                         candidate_state_sha256_value) -> dict:
    """Evidence of one official replay of recorded state.

    A verdict requires all of: a successful official process, the same task,
    a separate-mode verifier, a recorded regrade provenance chain naming the
    candidate trial, no agent phase in the replay trial, the candidate SUT
    identity carried through unchanged, the SUT stream copied verbatim rather
    than regenerated, a new trial environment, and consistent reward evidence.
    Anything else raises, so partial replays can never yield a verdict.

    An installed sandbox-state candidate is recorded as ``SEEDED``: the recorded
    artifact bytes were seeded into a fresh verifier environment. There is no
    patch, so the patch track's ``APPLIED`` label must not appear here, and the
    absence of an agent phase is reported as the recorded absence it is rather
    than as the name of the agent Harbor happens to instantiate internally.
    """
    trial_dir = Path(trial_dir)
    # Reward/task/exit/exception/id shape comes from the frozen preflight; this
    # function only adds what that preflight leaves unproven (see its docstring).
    reward = parse_terminal_reward_preflight(trial_dir, task_id, exit_code)
    raw = _load_json(trial_dir / "result.json")
    if raw.get("verifier_environment_mode") != "separate":
        raise ValueError("TERMINAL_REPLAY_NOT_SEPARATE_VERIFIER")

    config = raw.get("config") or {}
    source = config.get("source_trial") or {}
    if (source.get("action") != REGRADE_ACTION
            or source.get("type") != REGRADE_SOURCE_TYPE
            or not source.get("path")
            or Path(source["path"]).resolve() != Path(source_trial_dir).resolve()):
        raise ValueError("TERMINAL_REPLAY_NOT_A_REGRADE_OF_THE_SOURCE_TRIAL")

    # A regrade trial runs no agent phase: ``agent_execution`` is never set and
    # agent/ is the recorded tree, so the SUT stream must be byte-identical.
    if raw.get("agent_execution") is not None:
        raise ValueError("TERMINAL_REPLAY_UNEXPECTED_AGENT_PHASE")
    agent_info = raw.get("agent_info") or {}
    if (agent_info.get("name") != SUT_AGENT_NAME
            or agent_info.get("version") != SUT_AGENT_VERSION
            or agent_info.get("model_info", {}).get("name") != SUT_MODEL_LABEL):
        raise ValueError(
            f"TERMINAL_REPLAY_SUT_IDENTITY_CHANGED: {agent_info.get('name')}"
            f"@{agent_info.get('version')}")
    replay_stream = trial_dir / "agent" / REPLAY_AGENT_STREAM
    if not replay_stream.is_file():
        raise ValueError("TERMINAL_REPLAY_SUT_STREAM_MISSING")
    replay_stream_sha = hashlib.sha256(replay_stream.read_bytes()).hexdigest()
    if replay_stream_sha != source_stream_sha256:
        raise ValueError("TERMINAL_REPLAY_SUT_STREAM_REGENERATED")

    if not source_trial_id or raw.get("id") == source_trial_id:
        raise ValueError("TERMINAL_REPLAY_SANDBOX_NOT_INDEPENDENT")

    return {
        "status": reward["status"],
        "resolved": reward["resolved"],
        "candidate_artifact_type": SANDBOX_STATE_ARTIFACT,
        "candidate_identity_kind": "SANDBOX_STATE_TREE",
        "patch_apply_status": SANDBOX_STATE_INSTALL_STATUS,
        "sandbox_identity": raw.get("id"),
        "sandbox_identity_kind": "harbor_trial_id",
        "candidate_patch_sha256": candidate_state_sha256_value,
        "official_grader_executed": True,
        "official_grader_process_proven": True,
        "official_grader_agent_phase": "NOT_EXECUTED",
        "replay_agent_phase_executed": raw.get("agent_execution") is not None,
        "replay_source_trial_id": source_trial_id,
        "replay_source_trial_path": str(Path(source_trial_dir).resolve()),
        "replay_sut_identity": SUT_AGENT_NAME,
        "replay_sut_stream_sha256": replay_stream_sha,
        "raw_result_path": str(trial_dir / "result.json"),
    }


# ---------------------------------------------------------------------------
# Harbor agent plugin: the candidate-phase Code profile bridge
# ---------------------------------------------------------------------------

if HARBOR_AVAILABLE:
    _PluginBase = _HarborBaseAgent
else:  # pragma: no cover - stand-in keeps the classes importable for tests
    _PluginBase = _HarborBaseAgent


class _AdapterBase(_PluginBase):
    """Constructor handling shared by the plugin and host-side tests."""

    def _init_adapter(self, kwargs: dict, required: tuple[str, ...]) -> None:
        for key in required:
            value = kwargs.pop(key, None)
            if value is None:
                raise ValueError(f"TERMINAL_REPLAY_AGENT_KWARG_MISSING: {key}")
            setattr(self, f"_{key}", value)
        if HARBOR_AVAILABLE:
            super().__init__(*self._plugin_args, **kwargs)
        else:  # host-side construction (tests, static checks)
            logs_dir = kwargs.get("logs_dir")
            self.logs_dir = Path(logs_dir) if logs_dir else Path(
                tempfile.mkdtemp(prefix="terminal-replay-logs-")) / "agent"
            self.logger = logger


def discover_main_container(session_id: str) -> str:
    """The single ``main`` service container of a Harbor compose project."""
    try:  # exact upstream rule when Harbor is importable
        from harbor.environments.docker.docker import (
            _sanitize_docker_compose_project_name as sanitize)
    except Exception:  # pragma: no cover - host-side fallback
        import re
        def sanitize(name: str) -> str:
            name = name.lower()
            if not re.match(r"^[a-z0-9]", name):
                name = "0" + name
            return re.sub(r"[^a-z0-9_-]", "-", name)

    project = sanitize(session_id)
    result = subprocess.run(
        ["docker", "ps",
         "--filter", f"label=com.docker.compose.project={project}",
         "--filter", "label=com.docker.compose.service=main",
         "--format", "{{.Names}}"],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"TERMINAL_BRIDGE_DOCKER_UNAVAILABLE: {result.stderr.strip()}")
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(names) != 1:
        raise RuntimeError(
            f"TERMINAL_BRIDGE_CONTAINER_UNRESOLVED: matched={len(names)}")
    return names[0]


class HermesCodeHostAgent(_AdapterBase):
    """Candidate phase: Harbor manages the pinned task environment; the real,
    pinned host-side Hermes Code profile solves the task through a docker
    bridge. Harbor records the trial and collects the declared artifacts, so
    the resulting trial is an authentic source trial."""

    @staticmethod
    def name() -> str:
        return SUT_AGENT_NAME

    def version(self) -> str:
        return SUT_AGENT_VERSION

    def __init__(self, *args, sut_workspace: str | None = None,
                 sut_task_dir: str | None = None,
                 sut_timeout_sec: int | None = None, **kwargs):
        if sut_workspace is None or sut_task_dir is None or sut_timeout_sec is None:
            raise ValueError(
                "TERMINAL_REPLAY_AGENT_KWARG_MISSING: "
                "sut_workspace/sut_task_dir/sut_timeout_sec")
        self._plugin_args = args
        self._sut_workspace = sut_workspace
        self._sut_task_dir = sut_task_dir
        self._sut_timeout_sec = int(sut_timeout_sec)
        self._init_adapter(kwargs, ())

    async def setup(self, environment) -> None:
        pass

    async def run(self, instruction: str, environment, context) -> None:
        repo_dir = Path(__file__).resolve().parent.parent
        workspace = Path(self._sut_workspace).resolve()
        task_dir = Path(self._sut_task_dir)
        logs_dir = Path(self.logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)

        from verify_agent_sandbox import prove_sandbox  # same scripts/ dir

        # Gold isolation: the macOS sandbox profile denies the benchmark repo,
        # the upstream cache (which holds the pinned task dir with its
        # solution/ and tests/) and the dataset cache; probes must pass or the
        # trial dies.
        prefix = prove_sandbox(workspace, task_dir, repo_dir)

        container = discover_main_container(getattr(environment, "session_id", ""))
        bin_dir = workspace / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        bridge = bin_dir / "cmain"
        bridge.write_text(f"#!/bin/sh\nexec docker exec {container} \"$@\"\n")
        bridge.chmod(0o755)

        prompt = build_terminal_prompt(instruction)
        argv = build_sut_command(prompt, task_dir / "agent-sandbox.sb")
        env = {**os.environ, **SUT_EXTRA_ENV}

        stream_path = logs_dir / REPLAY_AGENT_STREAM
        stderr_path = logs_dir / "hermes-stderr.log"

        def _blocking():
            started = time.monotonic()
            with stream_path.open("w", encoding="utf-8") as out, \
                    stderr_path.open("w", encoding="utf-8") as err:
                try:
                    proc = subprocess.run([*prefix, *argv], cwd=str(workspace), env=env,
                                          stdout=out, stderr=err,
                                          timeout=self._sut_timeout_sec)
                    record = {"exit_code": proc.returncode, "timed_out": False,
                              "error": None}
                except subprocess.TimeoutExpired:
                    record = {"exit_code": None, "timed_out": True,
                              "error": "SUT exceeded the configured timeout"}
            record["duration_ms"] = round((time.monotonic() - started) * 1000)
            return record

        record = await asyncio.get_running_loop().run_in_executor(None, _blocking)
        record.update({"argv": argv, "cwd": str(workspace), "container": container,
                       "sut_stream": str(stream_path)})
        (logs_dir / REPLAY_PROCESS_RECORD).write_text(json.dumps(record, indent=2))
        if record["exit_code"] != 0:
            raise RuntimeError(
                f"HERMES_SUT_RUN_FAILED: exit={record['exit_code']} "
                f"timed_out={record['timed_out']} see {stderr_path}")
