"""Realistic sensor model based on the Rieger et al. sensor-class framework.

A sensor maps a true process signal to what an instrument reports, applying — in order —
response dynamics, measurement noise, detection-limit flooring, measuring-range clipping,
discrete sampling (zero-order hold), and optional quantization. The "ideal" path is the
phase-1 ``IdentitySensor`` (selected by ``measurement.mode='ideal'``); this module is the
``'realistic'`` path.

The signature matches the phase-1 seam: ``observe(channel, values, t)`` receives the full
1-D trajectory of one channel and its time axis (days), so dynamics/sampling are applied
vectorized over the whole series.

Sensor classes (Rieger; response time tr in minutes, n first-order lags, sample interval
ti): the n-lag cascade ``1/(1+tau s)^n`` has its 90-110% band response time equal to tr
when ``tau = tr / divisor(n)``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import lfilter, lfilter_zi

from .noise import band_limited_noise

# class -> (response time tr [min], number of first-order lags n, sample interval ti [min], unit delay)
SENSOR_CLASSES: dict[str, dict[str, Any]] = {
    "A": {"tr": 1.0, "n": 2, "ti": 0.0, "delay": False},
    "B0": {"tr": 10.0, "n": 8, "ti": 0.0, "delay": False},
    "B1": {"tr": 10.0, "n": 8, "ti": 5.0, "delay": False},
    "C0": {"tr": 20.0, "n": 8, "ti": 0.0, "delay": False},
    "C1": {"tr": 20.0, "n": 8, "ti": 5.0, "delay": False},
    "D": {"tr": 30.0, "n": 0, "ti": 30.0, "delay": True},  # batch/lab: hold + 1-step delay
}
# divisor making the n-lag cascade reach the 90-110% band at tr.
_DIVISOR = {2: 3.89, 8: 11.7724}

# Default sensor assignment for the measurable ASM1 channels (Rieger / BSM1 §7).
DEFAULT_SENSORS: dict[str, dict[str, Any]] = {
    "S_NH": {"class": "B0", "range": (0.0, 50.0)},
    "S_NO": {"class": "B0", "range": (0.0, 20.0)},
    "S_O": {"class": "A", "range": (0.0, 10.0)},
    "TSS": {"class": "A", "range": (0.0, 200.0)},
    "Q": {"class": "A", "range": (0.0, 100000.0)},
    "S_PO4": {"class": "B1", "range": (0.0, 10.0)},
}

DEFAULT_NOISE_LEVEL = 0.025  # fraction of measuring range (std), all classes


def _tau_min(tr: float, n: int) -> float:
    if n <= 0:
        return 0.0
    return tr / _DIVISOR.get(n, 3.89)


def _cascade_zoh(u: np.ndarray, tau_min: float, n: int, dt_min: float) -> np.ndarray:
    """Apply an n-stage first-order lag (each exact-ZOH discretized) to a held input."""
    if n <= 0 or tau_min <= 0 or dt_min <= 0:
        return u.copy()
    a = float(np.exp(-dt_min / tau_min))
    b, a_coef = [1.0 - a], [1.0, -a]
    zi0 = lfilter_zi(b, a_coef)
    y = np.asarray(u, dtype=float)
    for _ in range(n):
        y, _ = lfilter(b, a_coef, y, zi=zi0 * y[0])  # steady-state init at first sample
    return y


def _zoh_sample(y: np.ndarray, t_days: np.ndarray, ti_min: float, *, delay: bool) -> np.ndarray:
    """Hold the most recent sample on a ``ti``-minute grid; optional one-step delay (class D)."""
    if ti_min <= 0:
        return y
    t_min = np.asarray(t_days, dtype=float) * 1440.0
    grid = np.arange(t_min[0], t_min[-1] + ti_min, ti_min)
    # sample value at each grid point = y at the latest sim-step <= grid point
    samp_idx = np.clip(np.searchsorted(t_min, grid, side="right") - 1, 0, len(t_min) - 1)
    sample_vals = y[samp_idx]
    # each output time takes its grid bucket's sample
    bucket = np.clip(np.searchsorted(grid, t_min, side="right") - 1, 0, len(grid) - 1)
    if delay:
        bucket = np.clip(bucket - 1, 0, len(grid) - 1)
    return sample_vals[bucket]


class RealisticSensor:
    """Configurable sensor model. Channels without config pass through unchanged."""

    def __init__(self, sensors: dict[str, dict[str, Any]] | None = None, *, seed: int = 0):
        # merge user overrides onto the defaults
        merged = {k: dict(v) for k, v in DEFAULT_SENSORS.items()}
        for ch, cfg in (sensors or {}).items():
            merged.setdefault(ch, {}).update(cfg)
        self.sensors = merged
        self.seed = seed

    def observe(self, channel: str, values: np.ndarray, t: np.ndarray) -> np.ndarray:
        base = channel.split(".")[-1]
        cfg = self.sensors.get(base)
        if cfg is None:
            return values  # no sensor configured on this channel -> ground truth passthrough

        cls = SENSOR_CLASSES[cfg.get("class", "A")]
        tr = float(cfg.get("tr", cls["tr"]))
        n = int(cfg.get("n", cls["n"]))
        ti = float(cfg.get("cadence_min", cfg.get("ti", cls["ti"])))
        delay = bool(cfg.get("delay", cls["delay"]))
        ymin, ymax = cfg.get("range", (0.0, float(np.nanmax(values)) or 1.0))
        nl = float(cfg.get("nl", DEFAULT_NOISE_LEVEL))
        lod = float(cfg.get("lod", ymin))
        q = float(cfg.get("quantize", 0.0))

        t = np.asarray(t, dtype=float)
        dt_min = float(np.median(np.diff(t)) * 1440.0) if len(t) > 1 else 0.0

        y = _cascade_zoh(np.asarray(values, dtype=float), _tau_min(tr, n), n, dt_min)
        y = y + band_limited_noise(base, t, nl * (ymax - ymin), self.seed)
        y = np.where(y < lod, lod, y)
        y = np.clip(y, ymin, ymax)
        y = _zoh_sample(y, t, ti, delay=delay)
        if q > 0:
            y = np.round(y / q) * q
        return y
