# Benchmark Protocol Specification

## 1. Scope and Objective
This benchmark measures the software engineering capability of the **Hermes Code Bot Harness** on canonical, third-party benchmark tasks under strict scientific isolation, deterministic sampling, and independent official grading.

**Formula**:
$$\text{Performance} = \mathcal{P}(\text{Hermes Code Bot Harness}, \text{Official Tasks}, \text{Official Sandboxes}, \text{Official Graders})$$

## 2. Invariants & Negative Constraints
1. **NO TASK INVENTION**: Only official tasks from canonical datasets are permitted.
2. **NO GRADER RE-IMPLEMENTATION**: Grading must be executed solely by official upstream evaluation infrastructure.
3. **NO GOLD LEAKAGE**: Gold patches, fixing commits, and oracle solutions are kept strictly in `benchmark-control/private-oracle/` and must never enter the agent context, prompt, memory, or reviewer context.
4. **NO AGENT SOLVER RUNNERS**: Benchmark-provided agent loops (e.g. baseline solvers) are prohibited.
5. **NO OVERRIDING OF OFFICIAL VERDICTS**: Our internal Fresh Reviewer passes do NOT override official test failures.
6. **NO TASK REPLACEMENT ON FAILURE**: Failed tasks remain failed and are recorded in the failure taxonomy.

## 3. Architecture & Physical Plane Isolation
- **Control Plane (`benchmark-control/`)**:
  - Official datasets, base repositories, verification scripts, Docker definitions, and private oracle references.
  - Strictly read-only to evaluation scripts; inaccessible to agent workspaces.
- **Agent Plane (`agent-workspaces/`)**:
  - Prepared repository at exact `base_commit` with task instruction and benchmark-permitted test files.
  - Zero presence of gold patches, PR solutions, or verifier test scripts that belong to evaluation phases.

## 4. Sampling Methodology (Protocol v1)
The benchmark evaluates exactly 20 tasks across 3 tracks:

### Track A: SWE-bench Verified (6 tasks)
- Canonical Dataset: `princeton-nlp/SWE-bench_Verified` (split: test, 500 tasks)
- Stratified deterministic sampling using canonical `difficulty` column:
  - 2 tasks from `<15 min fix` (Easy)
  - 2 tasks from `15 min - 1 hour` (Medium)
  - 2 tasks from `1-4 hours` (Hard)
- Random seed: `20260927`

### Track B: SWE-bench Pro V2 (10 tasks)
- Canonical Dataset: `SWE-bench_Pro-os` (v2.0.0, 642 tasks)
- Stratified deterministic sampling:
  - 6 tasks from general validated V2 pool
  - 4 tasks from the official `v2/hard51_ids.txt` challenge set
- Random seed: `20260927`

### Track C: Terminal-Bench (4 tasks)
- Canonical Dataset: `terminal-bench/terminal-bench`
- Pre-filtering exclusions (defined before sampling):
  - Exclude tasks requiring external proprietary APIs (e.g., AWS/GCP live credentials).
  - Exclude tasks with unresolvable hardware constraints (e.g., bare-metal GPU requirements).
- Deterministic random selection of 4 tasks.
- Random seed: `20260927`

## 5. Execution Pipeline
Each task follows a strictly auditable 4-stage lifecycle:
1. **Workspace Preparation**:
   - Restore target repository to canonical `base_commit`.
   - Inject task instructions and start clean git worktree.
2. **Harness Problem Solving**:
   - Autonomous problem understanding, RED test reproduction, minimal fix implementation, and local regression testing.
   - Optional sub-mechanisms: Kanban DAG decomposition (max parallel workers = 2), Goal Mode continuation, and Fresh Reviewer audit.
3. **Candidate Export**:
   - SWE-bench Verified and Pro V2: generate a pristine unified Git diff (`GIT_PATCH`).
   - Terminal-Bench: retain the official Harbor source trial and all declared main/sidecar artifacts (`SANDBOX_STATE`). A `/app` Git diff is not a Terminal candidate.
4. **Official Grading**:
   - Execute official verifier (in pristine container or fresh sandbox).
   - Record raw outputs, pass/fail status, execution time, and full machine-readable telemetry.

## 6. Official Grader Prior Validation
Before running any scored task:
- Verify that reference patch (oracle) yields `PASS`.
- Verify that empty/no-op patch yields `FAIL`.
- For Terminal-Bench, verify oracle stability across consecutive runs. If the official oracle itself fails, the task is flagged `INFRA_INVALID`.

## 7. Telemetry & Machine-Captured Auditing
For every task run, the following files are mechanically captured under `runs/<run_id>/tasks/<task_id>/`:
- `task-manifest.json`: Static metadata, commit hashes, environment specs.
- `timeline.jsonl`: Timestamped lifecycle events.
- `decision-log.md`: Human-readable engineering rationale (why bug/feature, seam choice, review verdict).
- `tool-usage.json`: Mechanical count of tool calls.
- `skill-usage.json`: Recorded skill invocations.
- `mcp-usage.json`: MCP server and method logs.
- `kanban-events.jsonl`: Structured cards, transitions, and DAG events.
- `git-events.jsonl`: Worktree creations, commits, diffs.
- `test-events.jsonl`: Local test command executions, exit codes, and outputs.
- `review-events.jsonl`: Fresh Reviewer findings, severity, and repair loops.
- `patch.diff`: The exact candidate patch for SWE-bench tasks; Terminal-Bench requires an official Harbor source trial instead.
- `grader-result.json`: Official evaluation output from upstream verifier.
- `task-summary.json`: Final outcome metrics.

## 8. Failure Taxonomy
- `AGENT_FAIL`: Agent produced invalid patch or failed internal checks.
- `GRADER_FAIL`: Agent believed task was resolved, but official benchmark verifier failed.
- `TIMEOUT`: Execution exceeded task runtime limit.
- `INFRA_FAIL`: Container runtime, dependency download, or host failure.
- `INFRA_INVALID`: Official benchmark oracle itself fails on the task.
- `CONTAMINATED`: Accidental leakage of gold patch or reference solution into agent context.
- `PROTOCOL_INVALIDATED`: Mutation of SUT configuration during a frozen run.

## 9. Stop Conditions
A benchmark run is immediately halted if:
- Benchmark base commit or dataset revision cannot be pinned.
- Gold reference cannot be physically isolated.
- Upstream grader has been tampered with or modified.
- Environment requires unofficial agent solvers.

## 10. Measurement integrity addendum (protocol v2)

`PROTOCOL_V2.json` freezes the SUT identity, approval and 60-turn policy, source pins, harness files, and hashes of external configuration. `scripts/verify_protocol_freeze.py` requires a clean local checkout, an annotated tag at the exact current commit, a matching remote tag and branch, unchanged external configuration, and an unused run ID before calibration can start. The tag establishes a Git-history boundary; it does not certify grader execution by itself.

Each task must retain a clean base identity, a benchmark-native candidate, a Hermes raw stream, and official grader process/result evidence. SWE-bench tasks require the same patch in two independent official grading environments. Terminal-Bench requires the complete official Harbor trial (including sidecar artifacts and `artifacts/manifest.json`); the pinned Harbor source supports a separate-verifier regrade from that trial. A regrade may be called fresh replay only after it actually runs in a distinct trial. Missing evidence yields `INVALID` or `INFRA_FAIL`, never an inferred failure or success score. A grader `FAIL` can still be calibration infrastructure valid.

The exact production Hermes Code profile has not been proven runnable inside the official Harbor agent trial, so Terminal-Bench calibration remains blocked before any task starts. The Code profile's Goal loop is not entered by the current quiet CLI command; its DB stores a final snapshot, not an authoritative lifecycle. Fresh Reviewer read-only/exact-SHA execution has no authoritative per-task signal. These telemetry gaps do not substitute for grader evidence and do not by themselves invalidate calibration. No scored run may start under this repair branch before three infrastructure-valid calibration tasks and fresh exact-SHA review.
