"""Seeded, band-limited measurement noise.

Reproduces the BSM band-limiting trick: draw white Gaussian noise on a fixed 1-minute
grid (per channel, seeded) and linearly interpolate to the simulation timestep. This
makes the noise reproducible and independent of the simulation cadence, and decorrelates
channels (each uses a distinct seed).
"""

from __future__ import annotations

import numpy as np

_MASK = 0xFFFFFFFF


def channel_seed(channel: str, base_seed: int) -> int:
    """Deterministic per-channel seed (stable across runs, distinct per channel)."""
    h = 1469598103934665603  # FNV-1a offset basis (64-bit)
    for b in channel.encode("utf-8"):
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return int((h ^ (base_seed & _MASK)) & _MASK)


def band_limited_noise(channel: str, t_days: np.ndarray, sigma: float, base_seed: int) -> np.ndarray:
    """Band-limited Gaussian noise of std ``sigma`` evaluated at times ``t_days``.

    White noise is sampled on a 1-minute grid (seeded by channel + base_seed) and linearly
    interpolated onto ``t_days`` (band-limiting). Returns zeros if sigma <= 0.
    """
    if sigma <= 0:
        return np.zeros_like(t_days)
    rng = np.random.RandomState(channel_seed(channel, base_seed))
    t_min = np.asarray(t_days, dtype=float) * 1440.0
    grid = np.arange(np.floor(t_min[0]), np.ceil(t_min[-1]) + 1.0, 1.0)
    white = rng.standard_normal(len(grid))
    return sigma * np.interp(t_min, grid, white)
