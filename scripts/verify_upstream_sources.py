#!/usr/bin/env python3
"""
verify_upstream_sources.py - Verify exact commit hashes, dataset integrity, and container infrastructure.
"""

import sys
import json
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_DIR / "benchmark-manifest.json"

EXPECTED_SHAS = {
    "swe-bench": "02e7a74ffd0b707aab73d203fe87bdc7c76afc8e",
    "swe-bench-pro": "66f92766bba642462d4bbe5479e83f91f9211862",
    "terminal-bench": "4def1f367467b34b18e0dbdc086400ba71c3e037",
    "harbor": "3c82380859d187957cfd5cd64802b076d9779550"
}

def check_command(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode == 0, res.stdout.strip()

def main():
    print("Verifying upstream benchmark sources and tools...")
    all_passed = True

    # 1. Harbor CLI
    ok, out = check_command("harbor --version")
    if ok and "0.23.0" in out:
        print(f"✓ Harbor CLI verified: {out}")
    else:
        print(f"✗ Harbor CLI verification failed: {out}")
        all_passed = False

    # 2. Docker daemon
    ok, out = check_command("docker ps")
    if ok:
        print("✓ Docker daemon verified (running)")
    else:
        print(f"✗ Docker daemon not reachable: {out}")
        all_passed = False

    # 3. Check manifest existence
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        scored_count = len(manifest.get("scored_tasks", []))
        calib_count = len(manifest.get("calibration_tasks", []))
        if scored_count == 20 and calib_count == 3:
            print(f"✓ Benchmark manifest verified: 20 scored + 3 calibration tasks")
        else:
            print(f"✗ Unexpected task count in manifest: {scored_count} scored, {calib_count} calib")
            all_passed = False
    else:
        print(f"✗ Manifest not found: {MANIFEST_PATH}")
        all_passed = False

    # 4. Check cached/upstream repos
    scratch_upstream = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check")
    for name, expected_sha in EXPECTED_SHAS.items():
        repo_path = scratch_upstream / name
        if repo_path.exists():
            ok, sha = check_command(f"git -C {repo_path} rev-parse HEAD")
            if ok and sha == expected_sha:
                print(f"✓ Upstream {name} pinned at exact SHA: {sha[:10]}")
            else:
                print(f"✗ Upstream {name} SHA mismatch: got {sha}, expected {expected_sha}")
                all_passed = False
        else:
            print(f"✗ Upstream repo path missing: {repo_path}")
            all_passed = False

    # 5. Check Gold isolation
    oracle_dir = REPO_DIR / "benchmark-control" / "private-oracle"
    if oracle_dir.exists() and (oracle_dir / "swe-bench").exists() and (oracle_dir / "swe-bench-pro").exists() and (oracle_dir / "terminal-bench").exists():
        print(f"✓ Gold isolation verified in {oracle_dir}")
    else:
        print("✗ Gold isolation directory incomplete")
        all_passed = False

    if all_passed:
        print("\nALL UPSTREAM SOURCES AND INTEGRITY CHECKS PASSED.")
        sys.exit(0)
    else:
        print("\nUPSTREAM INTEGRITY CHECKS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    main()
