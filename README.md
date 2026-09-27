# Hermes Code Agent Benchmark

A public, reproducible, and third-party auditable software engineering benchmark for evaluating the **Hermes Code Bot Harness**.

This harness includes:
- **Hermes Code Bot SOUL & Global Engineering Governance** (`agent-engineering-governance`)
- **Reasoning Model & Execution Harness** (`gemini-3.8-flash-tiered`)
- **Autonomous Tooling & Workflow Primitives** (Goal Mode, Kanban DAG, Worktrees, Fresh Reviewer, Skills, MCP)

---

## Benchmark Tracks (20 Scored Tasks)

| Track | Benchmark Source | Dataset Reference | Sampled Scope |
| :--- | :--- | :--- | :--- |
| **Track A** | [SWE-bench Verified](https://github.com/princeton-nlp/SWE-bench) | `princeton-nlp/SWE-bench_Verified` | 6 instances (stratified 2 Easy / 2 Medium / 2 Hard) |
| **Track B** | [SWE-bench Pro V2](https://github.com/scaleapi/SWE-bench_Pro-os) | `SWE-bench_Pro-os` (`v2.0.0`) | 10 instances (6 standard V2 + 4 Hard-51) |
| **Track C** | [Terminal-Bench](https://github.com/harbor-framework/terminal-bench) | `harbor-framework/terminal-bench` | 4 instances (sandboxed system/dev tasks) |

---

## Core Principles

1. **The Benchmark is the Grader; Hermes is the Student**:
   - Official benchmarks provide only task definitions, sandboxes, and verifiers.
   - All understanding, planning, coding, review, and repair are performed autonomously by the Hermes harness.
   - No benchmark-provided agent runners or reference solution loops are permitted.
2. **Physical Isolation of Oracles**:
   - Reference patches and gold solutions are strictly stored in `benchmark-control/private-oracle` and never mounted or exposed to the agent.
3. **Reproducibility & Auditability**:
   - Every run records full machine telemetry (`timeline.jsonl`, `tool-usage.json`, `git-events.jsonl`, `test-events.jsonl`, etc.).
   - Exact commits, hashes, and patches are versioned and tagged.
4. **Honest Accounting**:
   - No task replacements on failure. A reproducible fail is infinitely more valuable than an unverified pass.

---

## Repository Structure

```
├── BENCHMARK_PROTOCOL.md            # Execution protocol, sampling rules, and invariants
├── BENCHMARK_SOURCES.md             # Canonical upstream repositories, SHAs, and datasets
├── SYSTEM_UNDER_TEST.md             # Configuration and exact SHA hashes of the harness
├── benchmark-manifest.json          # Pinned manifest of all 20 evaluated tasks
├── system-under-test.json           # Machine-readable harness specifications
├── governance-manifest.json         # Pinned agent-engineering-governance commit and rules
├── tool-inventory.json              # Available tool inventory and security policies
├── skill-inventory.json             # Pinned skill inventory and hashes
├── mcp-inventory.json               # Configured MCP servers
├── environment-manifest.json        # Host, container runtime, and tool versions
├── benchmark-cache-manifest.json    # Cached container images and base repos
├── benchmarks/                      # Pinned upstream repositories and task packages
├── benchmark-control/               # Isolated verification scripts and private oracles
├── scripts/                         # Benchmark automation scripts
│   ├── acquire_benchmarks.py        # Clone and verify upstream benchmark sources
│   ├── verify_upstream_sources.py   # Integrity verification of upstream repositories
│   ├── verify_official_graders.py   # Prior validation of official evaluators
│   ├── select_tasks.py              # Deterministic task selection script
│   ├── prepare_agent_workspace.py   # Workspace initialization and base checkout
│   ├── run_codebot_task.py          # Harness task executor and telemetry logger
│   ├── collect_telemetry.py         # Telemetry aggregation and validation
│   ├── export_candidate_patch.py    # Patch extractor from agent worktree
│   ├── grade_with_official_verifier.py # Official grader invocation
│   ├── fresh_sandbox_regrade.py     # Clean environment re-verification
│   └── build_report.py              # Metric compilation and report generation
├── runs/                            # Per-task execution trajectories and telemetry
└── reports/                         # Interim and final evaluation reports
```

---

## Auditing a Run

To reproduce and verify any evaluation result independently:
```bash
git clone https://github.com/FlapPearLabs/hermes-code-agent-benchmark.git
cd hermes-code-agent-benchmark
git checkout <run_tag_or_sha>

# Verify upstream integrity
python scripts/verify_upstream_sources.py

# Re-grade a candidate patch against the pristine official verifier
python scripts/grade_with_official_verifier.py --task <task_id> --patch runs/<run_id>/tasks/<task_id>/patch.diff
```
