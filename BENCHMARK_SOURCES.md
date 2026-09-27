# Canonical Benchmark Sources

This repository uses strictly official, canonical upstream benchmark sources. No unofficial forks or modified graders are permitted.

---

## 1. Track A — SWE-bench Verified

- **NAME**: `SWE-bench Verified`
- **CANONICAL_REPOSITORY**: `https://github.com/princeton-nlp/SWE-bench`
- **UPSTREAM_EXACT_SHA**: `02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`
- **DATASET_SOURCE**: Hugging Face `princeton-nlp/SWE-bench_Verified`
- **DATASET_VERSION**: `split: test` (500 canonical verified instances)
- **LICENSE**: MIT License
- **TASK_ACQUISITION_METHOD**: Official Hugging Face dataset stream via pinned `datasets` library; base repos cloned at exact `base_commit`.
- **ENVIRONMENT_SETUP_METHOD**: Official Docker container images built via `swebench.harness.docker_build` / official prebuilt environment containers.
- **OFFICIAL_GRADER_PATH**: `swebench.harness.run_evaluation`
- **ORACLE_PATH**: Canonical `patch` field in Hugging Face dataset (retained strictly in `benchmark-control/private-oracle`).
- **REFERENCE_SOLUTION_STORAGE**: `benchmark-control/private-oracle/swe-bench/`
- **AGENT_EXECUTION_COMPONENT_USED**: `NO`
- **OFFICIAL_AGENT_RUNNER_USED**: `NO`
- **GRADING_COMMAND**: `python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --predictions_path <predictions_file> --run_id <run_id>`
- **REPRODUCTION_COMMAND**: `python scripts/grade_with_official_verifier.py --track swe-bench --task <task_id> --patch <patch_path>`

---

## 2. Track B — SWE-bench Pro V2

- **NAME**: `SWE-bench Pro V2`
- **CANONICAL_REPOSITORY**: `https://github.com/scaleapi/SWE-bench_Pro-os`
- **UPSTREAM_EXACT_SHA**: `66f92766bba642462d4bbe5479e83f91f9211862` (Tag: `v2.0.0`)
- **DATASET_SOURCE**: Hugging Face `ScaleAI/SWE-bench_Pro` & upstream repo `v2/tasks/`
- **DATASET_VERSION**: `v2.0.0` (642 total tasks, 51 hard tasks in `v2/hard51_ids.txt`)
- **LICENSE**: Apache-2.0 License
- **TASK_ACQUISITION_METHOD**: Direct clone of `SWE-bench_Pro-os` at tag `v2.0.0`; task definitions from `v2/tasks/`.
- **ENVIRONMENT_SETUP_METHOD**: Official prebuilt Docker container images defined in each task's `task.toml` under `ghcr.io/scaleapi/swe-bench_pro-v2:*`.
- **OFFICIAL_GRADER_PATH**: `v2/tooling/patch_replay.py` via Harbor runner
- **ORACLE_PATH**: `solution/` directory in each task directory (retained strictly in `benchmark-control/private-oracle`).
- **REFERENCE_SOLUTION_STORAGE**: `benchmark-control/private-oracle/swe-bench-pro/`
- **AGENT_EXECUTION_COMPONENT_USED**: `NO`
- **OFFICIAL_AGENT_RUNNER_USED**: `NO`
- **GRADING_COMMAND**: `PYTHONPATH=benchmarks/swe-bench-pro/v2/tooling harbor run -p benchmarks/swe-bench-pro/v2/tasks/<task_id> -e docker -a patch_replay:PatchReplayAgent --model replay --ak source_patch=<patch_file>`
- **REPRODUCTION_COMMAND**: `python scripts/fresh_sandbox_regrade.py --track swe-bench-pro --task <task_id> --patch <patch_file>`

---

## 3. Track C — Terminal-Bench

- **NAME**: `Terminal-Bench`
- **CANONICAL_REPOSITORY**: `https://github.com/harbor-framework/terminal-bench`
- **UPSTREAM_EXACT_SHA**: `4def1f367467b34b18e0dbdc086400ba71c3e037`
- **DATASET_SOURCE**: Upstream repository `tasks/` directory and `tasks/dataset.toml`
- **DATASET_VERSION**: Pinned git commit `4def1f367467b34b18e0dbdc086400ba71c3e037`
- **LICENSE**: MIT License
- **TASK_ACQUISITION_METHOD**: Pinned git repository clone.
- **ENVIRONMENT_SETUP_METHOD**: Docker containers specified in `tasks/<task_id>/environment/Dockerfile` managed by Harbor CLI.
- **OFFICIAL_GRADER_PATH**: `tasks/<task_id>/tests/test.sh` executed inside sandbox via Harbor verifier.
- **ORACLE_PATH**: `tasks/<task_id>/solution/solve.sh` (retained strictly in `benchmark-control/private-oracle`).
- **REFERENCE_SOLUTION_STORAGE**: `benchmark-control/private-oracle/terminal-bench/`
- **AGENT_EXECUTION_COMPONENT_USED**: `NO`
- **OFFICIAL_AGENT_RUNNER_USED**: `NO`
- **GRADING_COMMAND**: `harbor run -p benchmarks/terminal-bench/tasks/<task_id> -e docker --agent nop` (with candidate patch pre-applied to workspace)
- **REPRODUCTION_COMMAND**: `python scripts/grade_with_official_verifier.py --track terminal-bench --task <task_id> --patch <patch_file>`

---

## 4. Evaluation Framework — Harbor

- **NAME**: `Harbor Evaluation Framework`
- **CANONICAL_REPOSITORY**: `https://github.com/harbor-framework/harbor`
- **UPSTREAM_EXACT_SHA**: `3c82380859d187957cfd5cd64802b076d9779550`
- **HARBOR_VERSION**: `0.23.0`
- **HARBOR_BINARY_PATH**: `/Users/songshiyao/.local/bin/harbor`
- **INSTALL_METHOD**: `uv tool install harbor`
