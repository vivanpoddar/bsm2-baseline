#!/usr/bin/env python3
"""Convenience wrapper for `bsm2 scenarios` (multi-scenario / multi-realization).

Equivalent to: bsm2 scenarios <args>   (e.g. --config config/scenarios.yaml)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bsm2_baseline.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["scenarios", *sys.argv[1:]]))
