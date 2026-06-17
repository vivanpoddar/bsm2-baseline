"""Build, run, and capture a BSM2 scenario (baseline or perturbed).

The runner owns the simulation step loop (rather than calling the package's
``simulate()``, which blocks on ``plt.show()`` and only exports the summary indices).
It drives ``step()`` directly, routes the dissolved-oxygen setpoint through the
``Actuator`` seam and the measured signals through the ``Sensor`` seam, applies any
scenario perturbations (influent / kinetics / settling), and captures the full
per-timestep trajectories the engine records on its instance attributes.

Engine dispatch lives here: ``engine=bsm2_python`` is implemented; ``engine=qsdsan_bsm2``
is routed to the QSDsan backend (added in a later increment).
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

from . import scenarios as sc
from .config import Engine, ModelVariant, ScenarioConfig
from .interfaces import Actuator, Sensor
from .variables import ASM1_COMPONENTS

# The engine integrates these module-level init arrays *in place*, so without a reset a
# second run in the same interpreter would inherit the previous run's final state. We
# snapshot the pristine values at import and restore them before each run, which makes
# runs bit-for-bit deterministic in-process (not just across fresh processes).
_PRISTINE_INIT: tuple[tuple[object, str, np.ndarray], ...] = (
    (_adm1init, "DIGESTERINIT", _adm1init.DIGESTERINIT.copy()),
    (_primclarinit, "YINIT1", _primclarinit.YINIT1.copy()),
)

# ASM1 kinetic-parameter index for nitrifier max growth rate (MU_A).
_MU_A = 5
# settler.sedpar indices: [v0_max, v0, r_h, r_p, f_ns, X_t, X_t2]
_V0_MAX, _V0, _R_H, _R_P, _F_NS = 0, 1, 2, 3, 4


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
    streams: dict[str, np.ndarray]         # name -> (n, 21) measured stream
    true_streams: dict[str, np.ndarray]    # name -> (n, 21) ground-truth stream
    derived: dict[str, np.ndarray]         # name -> (n, 5) advanced quantities (ground truth)
    indices: dict[str, np.ndarray]         # 'IQI'/'EQI'/'OCI' -> (n,)
    do_setpoint_applied: np.ndarray        # (n,) applied DO setpoint [g(O2)/m3]
    event_labels: np.ndarray               # (n,) per-timestep scenario event label
    final_performance: dict[str, float]    # benchmark scalars over the eval window
    eval_window: tuple[float, float]       # (start_day, end_day)
    realization_id: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


# Final-performance scalar names, in the tuple order returned by get_final_performance().
_FINAL_PERF_KEYS = (
    "IQI", "EQI", "total_sludge_production", "total_TSS_mass", "carbon_mass",
    "CH4_production", "H2_production", "CO2_production", "gas_flow",
    "heat_demand", "mixing_energy", "pumping_energy", "aeration_energy", "OCI",
)


def _influent_arg(cfg: ScenarioConfig, influent_data: np.ndarray | None, realization_id: int = 0):
    """Resolve the ``data_in`` argument for the engine constructor."""
    if influent_data is not None:
        return influent_data
    inf = cfg.influent
    if inf.mode == "default":
        return None
    if inf.mode == "file":
        return inf.path
    if inf.mode == "generate":
        from .influent.generator import realization

        length_days = cfg.duration_days or inf.length_years * 364.0
        # generate one extra day so the engine endtime stays within the influent record
        gen_length = length_days + (1.0 if cfg.duration_days else 0.0)
        return realization(inf, gen_length, cfg.timestep_days, realization_id)
    raise ValueError(f"unknown influent.mode '{inf.mode}'")


def _build_model(cfg: ScenarioConfig, influent_data: np.ndarray | None, realization_id: int = 0):
    """Construct the chosen bsm2-python model from config (strictly ideal: no sensor noise)."""
    data_in = _influent_arg(cfg, influent_data, realization_id)
    timestep = cfg.timestep_days
    endtime = cfg.duration_days

    if cfg.variant is ModelVariant.CLOSED_LOOP:
        # use_noise=0 -> engine-internal sensor noise off; our measurement layer owns noise.
        model = BSM2CL(
            data_in=data_in, timestep=timestep, endtime=endtime, evaltime=cfg.eval_days,
            use_noise=0, noise_seed=cfg.seed,
        )
    else:
        model = BSM2OL(
            data_in=data_in, timestep=timestep, endtime=endtime, evaltime=cfg.eval_days,
        )

    _set_eval_window(model, cfg.eval_days)
    _apply_settler_config(model, cfg)
    _privatize_kinetics(model)
    return model


def _set_eval_window(model, eval_days: int) -> None:
    """Force the evaluation window to the *last* ``eval_days`` days (engine int-evaltime quirk)."""
    end = float(model.simtime[-1])
    start = max(float(model.simtime[0]), end - eval_days)
    model.evaltime = np.array([start, end])
    model.eval_idx = np.array(
        [int(np.where(model.simtime <= start)[0][-1]), int(np.where(model.simtime <= end)[0][-1])]
    )


def _apply_settler_config(model, cfg: ScenarioConfig) -> None:
    """Write the config's Takács parameters into the settler (private copy)."""
    sp = np.array(model.settler.sedpar, dtype=float, copy=True)
    s = cfg.settler
    sp[_V0_MAX], sp[_V0], sp[_R_H], sp[_R_P], sp[_F_NS] = s.v0_max, s.v0, s.r_h, s.r_p, s.f_ns
    model.settler.sedpar = sp


def _privatize_kinetics(model) -> None:
    """Give each reactor a private copy of its kinetic-parameter array.

    The engine shares module-level ``PARx`` arrays; mutating them for scenarios would leak
    globally. Private copies keep per-step perturbations local and deterministic.
    """
    for r in (model.reactor1, model.reactor2, model.reactor3, model.reactor4, model.reactor5):
        r.asm1par = np.array(r.asm1par, dtype=float, copy=True)


def run_scenario(
    cfg: ScenarioConfig,
    *,
    sensor: Sensor | None = None,
    actuator: Actuator | None = None,
    influent_data: np.ndarray | None = None,
    realization_id: int = 0,
    progress: bool = True,
) -> RunResult:
    """Run one scenario and return its captured trajectories.

    Parameters
    ----------
    cfg:
        The scenario to run.
    sensor / actuator:
        Measurement-layer implementations. Default to ideal passthrough (reproduces
        phase-1). The deferred fault module plugs in here.
    influent_data:
        Optional pre-built influent array (n, 22) to use instead of the configured source
        (e.g. a realization from the synthetic generator).
    realization_id:
        Index of this influent realization (recorded in the dataset).
    progress:
        Show a tqdm progress bar.
    """
    if cfg.engine is Engine.QSDSAN_BSM2:
        raise NotImplementedError(
            "The QSDsan bsm2P backend (phosphorus) is added in a later increment. "
            "Use engine='bsm2_python' for now."
        )

    # Build the measurement layer from config unless explicitly overridden. mode='ideal'
    # yields identity passthrough (reproduces phase-1); 'realistic' applies the sensor models.
    if sensor is None or actuator is None:
        from .measurement import build_actuator, build_sensor

        sensor = sensor or build_sensor(cfg.measurement, seed=cfg.seed)
        actuator = actuator or build_actuator(cfg.measurement)

    events = sc.expand_preset(cfg.scenario)
    if sc.requires_phosphorus(events) and cfg.engine is Engine.BSM2_PYTHON:
        raise ValueError(
            f"scenario '{cfg.scenario}' targets phosphorus, which the bsm2_python engine "
            "cannot represent. Use engine='qsdsan_bsm2'."
        )

    _reset_engine_state()
    model = _build_model(cfg, influent_data, realization_id)
    is_closed_loop = cfg.variant is ModelVariant.CLOSED_LOOP

    # Influent-level perturbations (cold temperature, storm flow) before stabilization.
    if events:
        model.y_in = sc.apply_influent_perturbations(model.y_in, model.data_time, events)

    if cfg.stabilize:
        model.stabilize()  # uses baseline kinetics/settling (no event active at t=0)

    # Capture baseline kinetic/settling values for per-step scenario scaling.
    base_mu_a = [float(r.asm1par[_MU_A]) for r in _reactors(model)]
    base_v0_max, base_v0, base_r_h = (
        float(model.settler.sedpar[_V0_MAX]),
        float(model.settler.sedpar[_V0]),
        float(model.settler.sedpar[_R_H]),
    )

    n = len(model.simtime)
    do_applied = np.zeros(n)

    iterator = enumerate(model.simtime)
    if progress:
        iterator = enumerate(tqdm(model.simtime, desc=cfg.name, unit="step"))

    for i, t in iterator:
        if events:
            _apply_process_perturbations(
                model, events, float(t), base_mu_a, base_v0_max, base_v0, base_r_h
            )
        if is_closed_loop:
            applied = actuator.command(DO_SETPOINT_CHANNEL, cfg.do_setpoint, float(t))
            do_applied[i] = applied
            model.step(i, applied)
        else:
            model.step(i)

    # Ground-truth trajectories recorded by the engine during the loop.
    true_streams = {
        "influent": np.asarray(model.y_in_all, dtype=float),
        "effluent": np.asarray(model.y_eff_all, dtype=float),
        "reactor1": np.asarray(model.y_out1_all, dtype=float),
        "reactor2": np.asarray(model.y_out2_all, dtype=float),
        "reactor3": np.asarray(model.y_out3_all, dtype=float),
        "reactor4": np.asarray(model.y_out4_all, dtype=float),
        "reactor5": np.asarray(model.y_out5_all, dtype=float),
        "settler_overflow": np.asarray(model.ys_of_all, dtype=float),
        "settler_recycle": np.asarray(model.ys_r_all, dtype=float),
        "settler_waste": np.asarray(model.ys_was_all, dtype=float),
        "dewatered_sludge": np.asarray(model.sludge_all, dtype=float),
    }

    # Measured streams: pass the plant-boundary signals through the sensor seam.
    streams: dict[str, np.ndarray] = {}
    for name, arr in true_streams.items():
        if name in {"influent", "effluent"}:
            streams[name] = _apply_sensor(sensor, name, arr, model.simtime)
        else:
            streams[name] = arr

    derived = {
        "influent": _advanced(model, true_streams["influent"]),
        "effluent": _advanced(model, true_streams["effluent"]),
    }
    indices = {
        "IQI": np.asarray(model.iqi_all, dtype=float),
        "EQI": np.asarray(model.eqi_all, dtype=float),
        "OCI": np.asarray(model.oci_all, dtype=float),
    }
    final_perf = dict(zip(_FINAL_PERF_KEYS, model.get_final_performance(), strict=True))

    meta = {
        "engine": cfg.engine.value,
        "bsm2_python_version": importlib.metadata.version("bsm2-python"),
        "n_timesteps": n,
        "timestep_days": cfg.timestep_days,
        "stabilized": bool(getattr(model, "stabilized", False)),
        "scenario": sc.describe(cfg.scenario),
        "measurement_mode": cfg.measurement.mode,
    }

    return RunResult(
        config=cfg,
        time=np.asarray(model.simtime, dtype=float),
        streams=streams,
        true_streams=true_streams,
        derived=derived,
        indices=indices,
        do_setpoint_applied=do_applied,
        event_labels=sc.event_label_array(events, model.simtime),
        final_performance={k: float(v) for k, v in final_perf.items()},
        eval_window=(float(model.evaltime[0]), float(model.evaltime[1])),
        realization_id=realization_id,
        meta=meta,
    )


def _reactors(model):
    return (model.reactor1, model.reactor2, model.reactor3, model.reactor4, model.reactor5)


def _apply_process_perturbations(
    model, events, t: float, base_mu_a, base_v0_max: float, base_v0: float, base_r_h: float
) -> None:
    """Set reactor kinetics and settler parameters for the events active at ``t``."""
    mu_factor = sc.nitrifier_mu_factor(events, t)
    for r, base in zip(_reactors(model), base_mu_a, strict=True):
        r.asm1par[_MU_A] = base * mu_factor

    s = sc.settler_param_factors(events, t)
    model.settler.sedpar[_V0_MAX] = base_v0_max * s["v0_factor"]
    model.settler.sedpar[_V0] = base_v0 * s["v0_factor"]
    model.settler.sedpar[_R_H] = base_r_h * s["r_h_factor"]


def _apply_sensor(sensor: Sensor, name: str, arr: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Apply the sensor transform column-by-column over the 21 ASM1 components."""
    out = arr.copy()
    for var in ASM1_COMPONENTS:
        out[:, var.index] = sensor.observe(f"{name}.{var.key}", arr[:, var.index], t)
    return out


def _advanced(model, arr: np.ndarray) -> np.ndarray:
    """Compute the 5 advanced quantities using the engine's own stoichiometry."""
    return np.asarray(model.performance.advanced_quantities(arr, ADVANCED_COMPONENTS), dtype=float)
