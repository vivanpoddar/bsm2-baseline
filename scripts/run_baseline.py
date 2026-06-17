#!/usr/bin/env python3
"""Single entry point: read a scenario config, run it, export the dataset, plot.

Usage:
    python scripts/run_baseline.py --config config/baseline.yaml
    python scripts/run_baseline.py --config config/smoke.yaml --no-plot
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running straight from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bsm2_baseline.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
