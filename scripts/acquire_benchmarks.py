#!/usr/bin/env python3
"""
acquire_benchmarks.py - Acquire canonical benchmark repositories, datasets, and tooling.
Pins exact upstream commits per Benchmark Protocol Phase 2 and 3.
"""

import os
import sys
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path("/Users/songshiyao/.hermes/profiles/code/cache/scratch/upstream-check")

UPSTREAM_REPOS = {
    "swe-bench": {
        "url": "https://github.com/princeton-nlp/SWE-bench.git",
        "pin_sha": "02e7a74ffd0b707aab73d203fe87bdc7c76afc8e"
    },
    "swe-bench-pro": {
        "url": "https://github.com/scaleapi/SWE-bench_Pro-os.git",
        "pin_sha": "66f92766bba642462d4bbe5479e83f91f9211862"
    },
    "terminal-bench": {
        "url": "https://github.com/harbor-framework/terminal-bench.git",
        "pin_sha": "4def1f367467b34b18e0dbdc086400ba71c3e037"
    },
    "harbor": {
        "url": "https://github.com/harbor-framework/harbor.git",
        "pin_sha": "3c82380859d187957cfd5cd64802b076d9779550"
    }
}

def acquire():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("Acquiring and verifying pinned upstream benchmark repositories...")
    
    for name, info in UPSTREAM_REPOS.items():
        dest = CACHE_DIR / name
        if not dest.exists():
            print(f"Cloning {name} from {info['url']}...")
            subprocess.run(f"git clone {info['url']} {dest}", shell=True, check=True)
        
        # Checkout exact pinned SHA
        print(f"Checking out pinned SHA {info['pin_sha'][:10]} for {name}...")
        subprocess.run(f"git -C {dest} checkout {info['pin_sha']}", shell=True, check=True)

    print("All benchmark repositories acquired and pinned successfully.")

if __name__ == "__main__":
    acquire()
