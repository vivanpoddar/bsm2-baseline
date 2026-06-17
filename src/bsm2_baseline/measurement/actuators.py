"""Realistic actuator model: first-order(/cascade) lag with output limits and slew rate.

A commanded value is clipped to the actuator's range, passed through a response lag, and
slew-limited. The signature matches the phase-1 seam: ``command(channel, value, t)`` is
called once per timestep with a scalar, so lag state is held per channel across calls.

NOTE on aeration: in the bsm2-python closed-loop engine, blower/KLa dynamics are modelled
*inside* the engine (its own Sensor/PID/Actuator on KLa). This harness-level actuator wraps
the *commanded control signal* routed through the seam (e.g. the dissolved-oxygen setpoint),
which is the documented insertion point for a future actuator-fault model (stuck / biased /
failed). The ideal path is the phase-1 ``IdentityActuator`` (``measurement.mode='ideal'``).
"""

from __future__ import annotations

import math
from typing import Any

# channel -> response model. tr [min], n lags, limits, slew [units/min] (0 = no slew limit).
DEFAULT_ACTUATORS: dict[str, dict[str, Any]] = {
    # DO setpoint routed through the seam: small tracking lag, valid DO range.
    "reactor4_DO_setpoint": {"tr": 0.0, "n": 1, "min": 0.0, "max": 5.0, "slew": 0.0},
    # KLa actuators (used when a backend drives KLa directly, e.g. open-loop / QSDsan).
    "kla": {"tr": 4.0, "n": 2, "min": 0.0, "max": 360.0, "slew": 0.0},
}
_DIVISOR = {1: 1.0, 2: 3.89}


class RealisticActuator:
    """Configurable actuator with per-channel lag state, limits, and optional slew."""

    def __init__(self, actuators: dict[str, dict[str, Any]] | None = None):
        merged = {k: dict(v) for k, v in DEFAULT_ACTUATORS.items()}
        for ch, cfg in (actuators or {}).items():
            merged.setdefault(ch, {}).update(cfg)
        self.actuators = merged
        self._state: dict[str, dict[str, Any]] = {}

    def command(self, channel: str, value: float, t: float) -> float:
        base = channel.split(".")[-1]
        cfg = self.actuators.get(base)
        if cfg is None:
            return value  # no actuator model on this channel -> passthrough

        lo, hi = float(cfg.get("min", -math.inf)), float(cfg.get("max", math.inf))
        tr = float(cfg.get("tr", 0.0))
        n = max(1, int(cfg.get("n", 1)))
        tau_min = tr / _DIVISOR.get(n, 3.89) if tr > 0 else 0.0
        slew = float(cfg.get("slew", 0.0))

        cmd = min(max(value, lo), hi)
        st = self._state.get(base)
        if st is None or t <= st["t"]:
            # first call (or non-advancing time): initialise at steady state
            self._state[base] = {"t": float(t), "x": [cmd] * n, "applied": cmd}
            return cmd

        dt_min = (float(t) - st["t"]) * 1440.0
        x = st["x"]
        if tau_min > 0 and dt_min > 0:
            a = math.exp(-dt_min / tau_min)
            prev = cmd
            for i in range(n):
                x[i] = a * x[i] + (1.0 - a) * prev
                prev = x[i]
            applied = x[-1]
        else:
            x = [cmd] * n
            applied = cmd

        if slew > 0 and dt_min > 0:
            max_step = slew * dt_min
            applied = min(max(applied, st["applied"] - max_step), st["applied"] + max_step)

        applied = min(max(applied, lo), hi)
        self._state[base] = {"t": float(t), "x": x, "applied": applied}
        return applied
