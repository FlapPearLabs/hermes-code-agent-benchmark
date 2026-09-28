#!/usr/bin/env python3
"""Reject the historical synthetic oracle-ready claim.

Prior oracle calibration requires real official evaluator runs with raw
evidence for each pinned family. The old script performed neither test.
"""

import sys

if __name__ == "__main__":
    sys.stderr.write(
        "PRIOR_GRADER_VALIDATION_NOT_PROVEN: historical READY/PASS fields had "
        "no official evaluator evidence. Run documented oracle/no-op checks "
        "and retain their raw artifacts before allowing scored tasks.\n"
    )
    sys.exit(2)
