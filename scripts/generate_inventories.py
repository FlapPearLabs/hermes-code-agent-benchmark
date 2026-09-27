import json
import yaml
import hashlib
import os
import subprocess
from pathlib import Path

repo_dir = Path("/Users/songshiyao/Desktop/Projects/hermes-code-agent-benchmark")
profile_dir = Path("/Users/songshiyao/.hermes/profiles/code")
gov_dir = Path("/Users/songshiyao/Desktop/Projects/agent-engineering-governance")

# 1. Hashes of Profile & Governance
soul_path = profile_dir / "SOUL.md"
config_path = profile_dir / "config.yaml"

with open(soul_path, "rb") as f:
    soul_sha256 = hashlib.sha256(f.read()).hexdigest()

with open(config_path, "rb") as f:
    config_sha256 = hashlib.sha256(f.read()).hexdigest()

gov_sha = subprocess.check_output(["git", "-C", str(gov_dir), "rev-parse", "HEAD"]).decode().strip()
hermes_sha = subprocess.check_output(["git", "-C", "/Users/songshiyao/.hermes/hermes-agent", "rev-parse", "HEAD"]).decode().strip()

with open(config_path) as f:
    config = yaml.safe_load(f)

# 2. MCP Inventory
mcp_servers = config.get("mcp_servers", {})
mcp_inv = {
    "total_servers": len(mcp_servers),
    "servers": mcp_servers,
    "policy": "Sandboxed, monitored, zero oracle access, strictly task-scoped"
}
with open(repo_dir / "mcp-inventory.json", "w") as f:
    json.dump(mcp_inv, f, indent=2)

# 3. Skill Inventory
skills_root = profile_dir / "skills"
skills_list = []
for cat_dir in sorted(skills_root.iterdir()):
    if cat_dir.is_dir() and not cat_dir.name.startswith("."):
        for s_dir in sorted(cat_dir.iterdir()):
            if s_dir.is_dir():
                s_md = s_dir / "SKILL.md"
                desc = "No description"
                s_sha = ""
                if s_md.exists():
                    raw = s_md.read_bytes()
                    s_sha = hashlib.sha256(raw).hexdigest()
                    for line in raw.decode(errors="ignore").splitlines()[:20]:
                        if line.startswith("description:"):
                            desc = line.split("description:", 1)[1].strip()
                            break
                skills_list.append({
                    "name": s_dir.name,
                    "category": cat_dir.name,
                    "sha256": s_sha,
                    "description": desc,
                    "path": str(s_dir)
                })

skill_inv = {
    "total_skills": len(skills_list),
    "skills": skills_list
}
with open(repo_dir / "skill-inventory.json", "w") as f:
    json.dump(skill_inv, f, indent=2)

# 4. Tool Inventory
tools_inv = {
    "built_in_tools": [
        "terminal", "read_file", "write_file", "patch", "search_files",
        "execute_code", "delegate_task", "clarify", "memory",
        "kanban_show", "kanban_list", "kanban_create", "kanban_complete",
        "kanban_block", "kanban_unblock", "kanban_comment", "kanban_attach",
        "kanban_attach_url", "kanban_attachments", "kanban_request_review",
        "kanban_request_changes", "kanban_link", "kanban_heartbeat",
        "skills_list", "skill_view", "skill_manage",
        "web_search", "web_extract", "browser_navigate", "browser_click",
        "browser_type", "browser_snapshot", "browser_console", "browser_vision"
    ],
    "mcp_tools": [
        "mcp__agentmemory__*", "mcp__chrome_devtools__*", "mcp__codegraph__*"
    ],
    "terminal_executables": [
        "git", "python3", "uv", "docker", "colima", "gh", "harbor"
    ],
    "policy": {
        "execution_mode": "supervised_or_autonomous_per_phase",
        "oracle_access_allowed": False,
        "official_agent_runner_used": False,
        "tampering_prohibited": True
    }
}
with open(repo_dir / "tool-inventory.json", "w") as f:
    json.dump(tools_inv, f, indent=2)

# 5. Model Routing
model_routing = {
    "default_model": config.get("model", {}).get("default", "gemini-3.8-flash-tiered"),
    "provider": config.get("model", {}).get("provider", "custom:antigravity"),
    "base_url": config.get("model", {}).get("base_url", "http://127.0.0.1:8045/v1"),
    "auxiliary": config.get("auxiliary", {}),
    "model_aliases": config.get("model_aliases", {}),
    "routing_freeze": True
}
with open(repo_dir / "model-routing.json", "w") as f:
    json.dump(model_routing, f, indent=2)

# 6. Governance Manifest
gov_manifest = {
    "governance_repo_path": str(gov_dir),
    "governance_git_sha": gov_sha,
    "core_invariants": [
        "PRE-REPAIR FAILURE EVIDENCE REQUIRED",
        "MINIMAL AUTHORIZED CHANGE",
        "FRESH REVIEWER RUNTIME REQUIRED",
        "NO ORACLE / GOLD LEAKAGE",
        "OFFICIAL GRADER IS OUTCOME AUTHORITY"
    ],
    "rules_path": str(gov_dir / "RULES.md"),
    "agents_path": str(gov_dir / "AGENTS.md")
}
with open(repo_dir / "governance-manifest.json", "w") as f:
    json.dump(gov_manifest, f, indent=2)

# 7. Environment Manifest
env_manifest = {
    "host_os": "macOS 26.2 (Darwin 25.3.0)",
    "arch": "arm64 (Apple Silicon M-series)",
    "container_runtime": "colima 0.10.1 / Docker 29.3.1 (qemu multi-arch arm64/amd64/386)",
    "python_version": "Python 3.13.12 (CPython)",
    "uv_version": "0.12.9",
    "git_version": subprocess.check_output(["git", "--version"]).decode().strip(),
    "gh_version": subprocess.check_output(["gh", "--version"]).decode().splitlines()[0],
    "harbor_version": subprocess.check_output(["harbor", "--version"]).decode().strip(),
    "hermes_version": "v0.21.5+3172.g79dbb14",
    "hermes_exact_sha": hermes_sha
}
with open(repo_dir / "environment-manifest.json", "w") as f:
    json.dump(env_manifest, f, indent=2)

# 8. System Under Test JSON
sut = {
    "system_name": "HERMES_CODE_BOT_HARNESS",
    "harness_components": {
        "hermes_agent_version": "v0.21.5+3172.g79dbb14",
        "hermes_agent_sha": hermes_sha,
        "code_profile_soul_sha256": soul_sha256,
        "code_profile_config_sha256": config_sha256,
        "governance_repo_sha": gov_sha,
        "model": config.get("model", {}).get("default", "gemini-3.8-flash-tiered"),
        "provider": config.get("model", {}).get("provider", "custom:antigravity"),
        "reasoning_effort": "high",
        "goal_mode": True,
        "kanban": True,
        "max_parallel_workers": 2,
        "fresh_reviewer_policy": "delegate_task read-only subagent with exact-sha binding",
        "repair_policy": "append-only repair commit for accepted findings with fresh re-review",
        "network_policy": "isolated per benchmark protocol; agent offline during execution where required",
        "official_agent_runner_used": False,
        "no_official_benchmark_agent_loop_is_used": True
    }
}
with open(repo_dir / "system-under-test.json", "w") as f:
    json.dump(sut, f, indent=2)

print("Generated manifests and inventories successfully!")
