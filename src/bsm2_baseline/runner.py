"""Build, run, and capture a BSM2 baseline scenario.

The runner owns the simulation step loop (rather than calling the package's
``simulate()``, which blocks on ``plt.show()`` and only exports the summary indices).
It drives ``step()`` directly, routes the dissolved-oxygen setpoint through the
``Actuator`` seam and the measured effluent through the ``Sensor`` seam, and captures
the full per-timestep trajectories that the engine records on its instance attributes.
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from typing import Any

import bsm2_python.bsm2.init.adm1init_bsm2 as _adm1init
import bsm2_python.bsm2.init.primclarinit_bsm2 as _primclarinit
import numpy as np
from bsm2_python import BSM2CL, BSM2OL
from tqdm import tqdm

from .config import ModelVariant, ScenarioConfig
from .interfaces import Actuator, IdentityActuator, IdentitySensor, Sensor
from .variables import ASM1_COMPONENTS

# The engine integrates these module-level init arrays *in place*, so without a reset a
# second run in the same interpreter would inherit the previous run's final state. We
# snapshot the pristine values at import and restore them before each run, which makes
# runs bit-for-bit deterministic in-process (not just across fresh processes).
_PRISTINE_INIT: tuple[tuple[object, str, np.ndarray], ...] = (
    (_adm1init, "DIGESTERINIT", _adm1init.DIGESTERINIT.copy()),
    (_primclarinit, "YINIT1", _primclarinit.YINIT1.copy()),
)


def _reset_engine_state() -> None:
    """Restore in-place-mutated engine init arrays to their pristine values."""
    for module, attr, pristine in _PRISTINE_INIT:
        getattr(module, attr)[:] = pristine

# Components requested from PlantPerformance.advanced_quantities, in the order that
# matches variables.DERIVED_QUANTITIES.
ADVANCED_COMPONENTS = ("kjeldahlN", "totalN", "COD", "BOD5", "X_TSS")

# Channel name for the dissolved-oxygen setpoint routed through the actuator seam.
DO_SETPOINT_CHANNEL = "reactor4_DO_setpoint"


@dataclass
class RunResult:
    """Captured trajectories and metadata from one scenario run."""

    config: ScenarioConfig
    time: np.ndarray                       # (n,) simulation time [d]
    streams: dict[str, np.ndarray]         # name -> (n, 21) ASM1 stream
    derived: dict[str, np.ndarray]         # name -> (n, 5) advanced quantities
    indices: dict[str, np.ndarray]         # 'IQI'/'EQI'/'OCI' -> (n,)
    do_setpoint_applied: np.ndarray        # (n,) applied DO setpoint [g(O2)/m3]
    final_performance: dict[str, float]    # benchmark scalars over the eval window
    eval_window: tuple[float, float]       # (start_day, end_day)
    meta: dict[str, Any] = field(default_factory=dict)


# Final-performance scalar names, in the tuple order returned by get_final_performance().
_FINAL_PERF_KEYS = (
    "IQI", "EQI", "total_sludge_production", "total_TSS_mass", "carbon_mass",
    "CH4_production", "H2_production", "CO2_production", "gas_flow",
    "heat_demand", "mixing_energy", "pumping_energy", "aeration_energy", "OCI",
)


def _build_model(cfg: ScenarioConfig):
    """Construct the chosen BSM2 model from config (strictly ideal: no sensor noise)."""
    data_in = None if cfg.influent == "default" else cfg.influent
    timestep = cfg.timestep_days
    endtime = cfg.duration_days

    if cfg.variant is ModelVariant.CLOSED_LOOP:
        # use_noise=0 -> ideal sensors, deterministic. seed wired for the future fault layer.
        model = BSM2CL(
            data_in=data_in,
            timestep=timestep,
            endtime=endtime,
            evaltime=cfg.eval_days,
            use_noise=0,
            noise_seed=cfg.seed,
        )
    else:
        model = BSM2OL(
            data_in=data_in,
            timestep=timestep,
            endtime=endtime,
            evaltime=cfg.eval_days,
        )

    _set_eval_window(model, cfg.eval_days)
    return model


def _set_eval_window(model, eval_days: int) -> None:
    """Force the evaluation window to the *last* ``eval_days`` days.

    Works around the package's integer-``evaltime`` handling, which sets the window to
    ``[eval_days, end]`` rather than the trailing ``eval_days``.
    """
    end = float(model.simtime[-1])
    start = max(float(model.simtime[0]), end - eval_days)
    model.evaltime = np.array([start, end])
    model.eval_idx = np.array(
        [
            int(np.where(model.simtime <= start)[0][-1]),
            int(np.where(model.simtime <= end)[0][-1]),
        ]
    )


def run_scenario(
    cfg: ScenarioConfig,
    *,
    sensor: Sensor | None = None,
    actuator: Actuator | None = None,
    progress: bool = True,
) -> RunResult:
    """Run one scenario and return its captured trajectories.

    Parameters
    ----------
    cfg:
        The scenario to run.
    sensor / actuator:
        Fault-seam implementations. Default to ideal passthrough; the baseline never
        passes anything else.
    progress:
        Show a tqdm progress bar.
    """
    sensor = sensor or IdentitySensor()
    actuator = actuator or IdentityActuator()

    _reset_engine_state()
    model = _build_model(cfg)
    is_closed_loop = cfg.variant is ModelVariant.CLOSED_LOOP

    if cfg.stabilize:
        model.stabilize()

    n = len(model.simtime)
    do_applied = np.zeros(n)

    iterator = enumerate(model.simtime)
    if progress:
        iterator = enumerate(tqdm(model.simtime, desc=cfg.name, unit="step"))

    for i, t in iterator:
        if is_closed_loop:
            # Route the commanded DO setpoint through the actuator seam (identity now).
            applied = actuator.command(DO_SETPOINT_CHANNEL, cfg.do_setpoint, float(t))
            do_applied[i] = applied
            model.step(i, applied)
        else:
            model.step(i)

    # The engine recorded full trajectories on these attributes during the loop.
    raw_streams = {
        "influent": model.y_in_all,
        "effluent": model.y_eff_all,
        "reactor1": model.y_out1_all,
        "reactor2": model.y_out2_all,
        "reactor3": model.y_out3_all,
        "reactor4": model.y_out4_all,
        "reactor5": model.y_out5_all,
        "settler_overflow": model.ys_of_all,    # clarified effluent before bypass merge
        "settler_recycle": model.ys_r_all,
        "settler_waste": model.ys_was_all,
        "dewatered_sludge": model.sludge_all,
    }

    # Pass measured streams through the sensor seam (identity now). Influent and effluent
    # are the "observed" plant boundary signals; internal reactor states are ground truth.
    streams: dict[str, np.ndarray] = {}
    for name, arr in raw_streams.items():
        arr = np.asarray(arr, dtype=float)
        if name in {"influent", "effluent"}:
            arr = _apply_sensor(sensor, name, arr, model.simtime)
        streams[name] = arr

    # Engine-consistent derived quantities (COD/BOD5/N/TSS) for influent and effluent.
    derived = {
        "influent": _advanced(model, streams["influent"]),
        "effluent": _advanced(model, streams["effluent"]),
    }

    indices = {
        "IQI": np.asarray(model.iqi_all, dtype=float),
        "EQI": np.asarray(model.eqi_all, dtype=float),
        "OCI": np.asarray(model.oci_all, dtype=float),
    }

    final_perf = dict(zip(_FINAL_PERF_KEYS, model.get_final_performance(), strict=True))

    meta = {
        "bsm2_python_version": importlib.metadata.version("bsm2-python"),
        "n_timesteps": n,
        "timestep_days": cfg.timestep_days,
        "stabilized": bool(getattr(model, "stabilized", False)),
    }

    return RunResult(
        config=cfg,
        time=np.asarray(model.simtime, dtype=float),
        streams=streams,
        derived=derived,
        indices=indices,
        do_setpoint_applied=do_applied,
        final_performance={k: float(v) for k, v in final_perf.items()},
        eval_window=(float(model.evaltime[0]), float(model.evaltime[1])),
        meta=meta,
    )


def _apply_sensor(sensor: Sensor, name: str, arr: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Apply the sensor transform column-by-column over the 21 ASM1 components."""
    out = arr.copy()
    for var in ASM1_COMPONENTS:
        idx = var.index
        out[:, idx] = sensor.observe(f"{name}.{var.key}", arr[:, idx], t)
    return out


def _advanced(model, arr: np.ndarray) -> np.ndarray:
    """Compute the 5 advanced quantities using the engine's own stoichiometry."""
    return np.asarray(
        model.performance.advanced_quantities(arr, ADVANCED_COMPONENTS), dtype=float
    )
