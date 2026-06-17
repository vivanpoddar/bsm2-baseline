"""Synthetic BSM2 influent generation (Gernaey phenomenological model).

``generate(length_days, seed, weather, n_realizations, dt)`` returns ASM1 21-component
influent (with a leading time column) that feeds the runner unchanged via
``influent.mode='generate'`` in the config.
"""

from __future__ import annotations

from .generator import generate, realization
from .params import InfluentParams

__all__ = ["InfluentParams", "generate", "realization"]
