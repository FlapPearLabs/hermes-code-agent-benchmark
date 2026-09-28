# System Under Test (SUT)

## Role Definition
**Hermes Code Bot is the exam taker.**
**The third-party benchmark is the exam paper, exam room, and official grader.**

`NO OFFICIAL BENCHMARK AGENT LOOP IS USED.`
`OFFICIAL_AGENT_RUNNER_USED = NO`

## System Specification
- **System Name**: `HERMES_CODE_BOT_HARNESS`
- **Hermes Version**: `v0.21.5+3172.g79dbb14 (2026.9.24)`
- **Hermes Commit**: `79dbb1450ec404a2240529f5554526da4cfec498`
- **Hermes Runtime Identity**: that upstream commit plus the accepted local `hermes_cli/gateway_launchd.py` patch (Git binary diff SHA256 `2460ba146aeb99fb533d8bbc1817b170fda9f6e26947201a6b42623538408704`). This is not a clean upstream checkout; `HERMES_RUNTIME_PATCH_MANIFEST.json` pins the exact tracked diff and untracked file set.
- **Bundled Skill Source**: 116 untracked runtime-repository files are byte-identical to active Code profile Skills. They remain in place because Hermes uses runtime `skills/` for startup sync and reset. `SKILL_COPY_OWNERSHIP_MANIFEST.json` pins every file, its active counterpart, and the profile Skill tree. The one untracked Gateway backup remains a declared generated artifact.
- **Default Model**: `gemini-3.8-flash-tiered`
- **Model Provider**: `custom:antigravity` (`http://127.0.0.1:8045/v1`)
- **Reasoning Effort**: `high`
- **Code Profile SOUL SHA256**: `2bd60a6faa55d7eefcc04d3a00a7fbdf9da19658fd81501144a03bb020ddc136`
- **Code Profile Config SHA256**: `837adc7ae1bdf394dc5864536700841dc2f549cbde2084bdc74624c480928ed1` (observed before protocol-v2 freeze)
- **Agent Engineering Governance Git SHA**: `6ebde952681486d7caaaf826bd2a77c96c3e13a8`

## Harness Components
- **Goal Mode**: Configured capability; the current quiet CLI runner does not enter its continuation loop without `HERMES_KANBAN_GOAL_MODE=1`. A session DB final snapshot can prove some positive observations but cannot reconstruct the lifecycle.
- **Kanban Orchestration**: Enabled (durable task DAG, worktree isolation; max parallel workers = 2).
- **Fresh Reviewer Runtime**: Declared policy; per-task independent read-only execution and exact-commit SHA binding are not mechanically observable from current stream/DB records (`TELEMETRY_UNAVAILABLE`).
- **Repair Policy**: Append-only repair commits for accepted reviewer findings, invalidating prior approval and re-triggering fresh review.
- **Skills**: Curated engineering skill suite (see `skill-inventory.json`).
- **MCP Servers**: Sandboxed local services (`agentmemory`, `chrome-devtools`, `codegraph`; see `mcp-inventory.json`).
- **Network Policy**: Isolated per benchmark protocol. No search for gold PRs, fixing commits, or external solutions during task solving.

Availability of Goal, Kanban, Skills, MCP, and Fresh Reviewer is not evidence that a task invoked them. The protocol-v2 runner records observed runtime events; when the runtime exposes no authoritative event, usage remains `TELEMETRY_UNAVAILABLE` rather than being inferred from this specification.

`SUT_SMOKE_EVIDENCE.json` records the production Code profile startup, Skill invocation, MCP inventory, and Kanban tool inventory checks. These prove the local profile still loads; they do not prove the Code profile can run unchanged inside a Terminal-Bench Harbor trial. Calibration remains gated on that exact-SUT trial adapter and authentic sidecar-state replay.

## Boundary Enforcement
The official benchmark infrastructure is strictly restricted to:
1. Environment setup and base commit checkout
2. Sandbox lifecycle management
3. Candidate patch application
4. Official test and verifier execution
5. Pass/Fail grading and report output

All task comprehension, architectural/seam analysis, planning, ticket decomposition, tool invocation, code modifications, test-driven debugging, and self-governed review are executed solely by the Hermes Code Bot Harness.
