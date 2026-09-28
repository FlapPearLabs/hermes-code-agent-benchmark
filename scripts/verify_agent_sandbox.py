#!/usr/bin/env python3
"""Prove that a Hermes subprocess can read its task but not benchmark controls."""

import json
import platform
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
LEGACY_REPO = Path("/Users/songshiyao/Desktop/Projects/hermes-code-agent-benchmark")
UPSTREAM_CACHE = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check")
DATASET_CACHE = Path("/Users/songshiyao/.cache/huggingface")
CODE_PROFILE = Path("/Users/songshiyao/.hermes/profiles/code")
GOVERNANCE_REPO = Path("/Users/songshiyao/Desktop/Projects/agent-engineering-governance")


def _scheme_path(path):
    return json.dumps(str(Path(path).resolve()))


def profile_for(workspace, benchmark_repo=REPO_DIR):
    wrapper = Path(workspace).resolve(strict=True)
    benchmark_repo = Path(benchmark_repo).resolve(strict=True)
    if not wrapper.is_relative_to(benchmark_repo / "agent-workspaces"):
        raise RuntimeError("AGENT_WORKSPACE_OUTSIDE_BENCHMARK")
    if not (wrapper / "PROBLEM.md").is_file() or not (wrapper / "repo").is_dir():
        raise RuntimeError("AGENT_WORKSPACE_INCOMPLETE")
    # Specific workspace allow rules override the broader control-plane deny.
    lines = ["(version 1)", "(allow default)",
             f"(deny file-read* (subpath {_scheme_path(benchmark_repo)}))",
             f"(deny file-write* (subpath {_scheme_path(benchmark_repo)}))",
             f"(allow file-read* (subpath {_scheme_path(wrapper)}))",
             f"(allow file-write* (subpath {_scheme_path(wrapper)}))"]
    for secret_root in (LEGACY_REPO, UPSTREAM_CACHE, DATASET_CACHE):
        root = secret_root.resolve()
        if root != benchmark_repo:
            lines.append(f"(deny file-read* (subpath {_scheme_path(root)}))")
            lines.append(f"(deny file-write* (subpath {_scheme_path(root)}))")
    for frozen_root in (CODE_PROFILE / "config.yaml", CODE_PROFILE / "SOUL.md", GOVERNANCE_REPO):
        lines.append(f"(deny file-write* (subpath {_scheme_path(frozen_root)}))")
    return "\n".join(lines) + "\n"


def prove_sandbox(workspace, task_dir, benchmark_repo=REPO_DIR):
    if platform.system() != "Darwin":
        raise RuntimeError("NO_VERIFIED_AGENT_SANDBOX_FOR_THIS_PLATFORM")
    task_dir = Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)
    profile_path = task_dir / "agent-sandbox.sb"
    profile_path.write_text(profile_for(workspace, benchmark_repo))
    prefix = ["sandbox-exec", "-f", str(profile_path)]
    allowed = Path(workspace) / "PROBLEM.md"
    denied = Path(benchmark_repo) / "benchmark-manifest.json"
    probes = {}
    for label, path in (("task_instruction", allowed), ("benchmark_control", denied)):
        result = subprocess.run(prefix + ["/bin/cat", str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        probes[label] = {"path": str(path), "exit_code": result.returncode}
    legacy_oracle = LEGACY_REPO / "benchmark-control" / "private-oracle"
    if legacy_oracle.is_dir():
        gold_files = [p for p in legacy_oracle.rglob("*") if p.is_file()]
        if gold_files:
            result = subprocess.run(prefix + ["/bin/cat", str(gold_files[0])],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            probes["legacy_oracle"] = {"path": str(gold_files[0]), "exit_code": result.returncode}
    passed = (probes["task_instruction"]["exit_code"] == 0 and
              probes["benchmark_control"]["exit_code"] != 0 and
              all(record["exit_code"] != 0 for name, record in probes.items()
                  if name == "legacy_oracle"))
    proof = {"status": "PASS" if passed else "FAIL", "profile": str(profile_path),
             "probes": probes}
    (task_dir / "agent-sandbox-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    if not passed:
        raise RuntimeError("AGENT_GOLD_ISOLATION_NOT_PROVEN")
    return prefix
