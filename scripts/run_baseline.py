#!/usr/bin/env python3
"""Convenience wrapper for `bsm2 run` (single scenario).

Equivalent to: bsm2 run <args>     (e.g. --config config/baseline.yaml)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bsm2_baseline.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
