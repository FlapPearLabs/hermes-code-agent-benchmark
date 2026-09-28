#!/usr/bin/env python3
"""Retired unsafe entrypoint. Use the calibration runner with a frozen run ID."""

import sys

if __name__ == "__main__":
    sys.stderr.write(
        "Direct run_codebot_task is disabled: the old path emitted synthetic "
        "classification and verdict records. Use chunked_benchmark_runner.py "
        "--stage calibration --run-id <new-run-id>.\n"
    )
    sys.exit(2)
