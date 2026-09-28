# Canonical Benchmark Sources

This repository uses strictly official, canonical upstream benchmark sources. No unofficial forks or modified graders are permitted.

---

## 1. Track A — SWE-bench Verified

- **NAME**: `SWE-bench Verified`
- **CANONICAL_REPOSITORY**: `https://github.com/princeton-nlp/SWE-bench`
- **UPSTREAM_EXACT_SHA**: `02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`
- **DATASET_SOURCE**: Hugging Face `princeton-nlp/SWE-bench_Verified`
- **DATASET_REVISION**: `c104f840cc67f8b6eec6f759ebc8b2693d585d4a` (local cache ref must match before grading)
- **DATASET_VERSION**: `split: test` (500 canonical verified instances)
- **LICENSE**: MIT License
- **TASK_ACQUISITION_METHOD**: Official Hugging Face dataset stream via pinned `datasets` library; base repos cloned at exact `base_commit`.
- **ENVIRONMENT_SETUP_METHOD**: Official Docker container images built via `swebench.harness.docker_build` / official prebuilt environment containers.
- **OFFICIAL_GRADER_PATH**: `swebench.harness.run_evaluation`
- **ORACLE_PATH**: Canonical `patch` field in Hugging Face dataset (retained strictly in `benchmark-control/private-oracle`).
- **REFERENCE_SOLUTION_STORAGE**: `benchmark-control/private-oracle/swe-bench/`
- **AGENT_EXECUTION_COMPONENT_USED**: `NO`
- **OFFICIAL_AGENT_RUNNER_USED**: `NO`
- **GRADING_COMMAND**: `python -m swebench.harness.run_evaluation --dataset_name <pinned-c104f840-test.parquet> --split test --predictions_path <predictions_file> --instance_ids <task_id> --run_id <run_id>` with Hugging Face offline mode (exact command and dataset file hash are recorded per task)
- **REPRODUCTION_COMMAND**: `python scripts/grade_with_official_verifier.py --run-id <run_id> --task <task_id>` (requires a valid exported patch and workspace manifest)

---

## 2. Track B — SWE-bench Pro V2

- **NAME**: `SWE-bench Pro V2`
- **CANONICAL_REPOSITORY**: `https://github.com/scaleapi/SWE-bench_Pro-os`
- **UPSTREAM_EXACT_SHA**: `66f92766bba642462d4bbe5479e83f91f9211862` (Tag: `v2.0.0`)
- **DATASET_SOURCE**: Hugging Face `ScaleAI/SWE-bench_Pro` & upstream repo `v2/tasks/`
- **DATASET_REVISION**: `2d52cb3df914a3fcf80c7f66738b3a88ae37fc50` (selection cache; grading uses pinned upstream task package)
- **DATASET_VERSION**: `v2.0.0` (642 total tasks, 51 hard tasks in `v2/hard51_ids.txt`)
- **LICENSE**: Apache-2.0 License
- **TASK_ACQUISITION_METHOD**: Direct clone of `SWE-bench_Pro-os` at tag `v2.0.0`; task definitions from `v2/tasks/`.
- **ENVIRONMENT_SETUP_METHOD**: Official prebuilt Docker container images defined in each task's `task.toml` under `ghcr.io/scaleapi/swe-bench_pro-v2:*`.
- **OFFICIAL_GRADER_PATH**: `v2/tooling/patch_replay.py` via Harbor runner
- **ORACLE_PATH**: `solution/` directory in each task directory (retained strictly in `benchmark-control/private-oracle`).
- **REFERENCE_SOLUTION_STORAGE**: `benchmark-control/private-oracle/swe-bench-pro/`
- **AGENT_EXECUTION_COMPONENT_USED**: `NO`
- **OFFICIAL_AGENT_RUNNER_USED**: `NO`
- **GRADING_COMMAND**: `PYTHONPATH=<pinned-v2/tooling> harbor run -p <pinned-v2/tasks/task_id> -e docker -a patch_replay:PatchReplayAgent --model replay --ak source_job=<source-job-dir>` (source job must contain `instance_*/result.json` and `agent/model.patch`; see recorded grader command)
- **REPRODUCTION_COMMAND**: `python scripts/fresh_sandbox_regrade.py --run-id <run_id> --task <task_id>`

---

## 3. Track C — Terminal-Bench

- **NAME**: `Terminal-Bench`
- **CANONICAL_REPOSITORY**: `https://github.com/harbor-framework/terminal-bench`
- **UPSTREAM_EXACT_SHA**: `4def1f367467b34b18e0dbdc086400ba71c3e037`
- **DATASET_SOURCE**: Upstream repository `tasks/` directory and `tasks/dataset.toml`
- **DATASET_VERSION**: Pinned git commit `4def1f367467b34b18e0dbdc086400ba71c3e037`
- **LICENSE**: MIT License
- **TASK_ACQUISITION_METHOD**: Pinned git repository clone.
- **ENVIRONMENT_SETUP_METHOD**: Official Harbor task environment, including Docker Compose services where the pinned task requires them.
- **OFFICIAL_GRADER_PATH**: `tasks/<task_id>/tests/test.sh` executed inside sandbox via Harbor verifier.
- **ORACLE_PATH**: `tasks/<task_id>/solution/solve.sh` (retained strictly in `benchmark-control/private-oracle`).
- **REFERENCE_SOLUTION_STORAGE**: `benchmark-control/private-oracle/terminal-bench/`
- **AGENT_EXECUTION_COMPONENT_USED**: `NO`
- **OFFICIAL_AGENT_RUNNER_USED**: `NO`
- **CANDIDATE_ARTIFACT_TYPE**: `SANDBOX_STATE` (official Harbor source trial and collected artifact manifest), not a Git patch. `payments-pipeline-fix` declares `/app/src/` and `kafka:/tmp/kafka-snapshot.tgz`; its verifier reads both from collected artifacts. Missing or corrupt Kafka snapshot is infrastructure invalid, not a task `FAIL`.
- **FRESH_REPLAY_SUPPORTED**: `YES`, conditional on an authentic complete source trial. Pinned Harbor provides `harbor trials regrade <source-trial-dir> -p <pinned-task-dir> -e docker --trial-name <new-name> -o <output-dir>` and rejects missing/failed artifact inputs. This is not evidence that a replay has occurred.
- **GRADING_STATUS**: `BLOCKED_EXACT_SUT_TRIAL`. Current host Hermes Code profile has not been reproduced inside a Harbor trial with equivalent model/MCP routing and isolation. Harbor's built-in Hermes agent is not the frozen SUT. The calibration runner therefore starts no task. `--agent nop` and a host `/app` patch omit the Kafka sidecar state.

---

## 4. Evaluation Framework — Harbor

- **NAME**: `Harbor Evaluation Framework`
- **CANONICAL_REPOSITORY**: `https://github.com/harbor-framework/harbor`
- **UPSTREAM_EXACT_SHA**: `3c82380859d187957cfd5cd64802b076d9779550`
- **HARBOR_VERSION**: `0.23.0`
- **HARBOR_BINARY_PATH**: `/Users/songshiyao/.local/bin/harbor`
- **INSTALL_METHOD**: `uv tool install harbor`
