"""Streamlit UI for the BSM2 simulation harness.

Three modes:
  - Run a scenario  : drive the bsm2_python / qsdsan_bsm2 engine live and visualise the
                      effluent-compliance trajectories (with scenario-event shading,
                      permit limits, and a true-vs-measured toggle).
  - Plant power use : run the BSM2OLEM energy model and visualise power / biogas / economics.
  - Explore dataset : load an already-generated dataset from ``data/`` without re-running.

Launch:  streamlit run ui/app.py    (after: pip install -e ".[ui]")
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Allow running straight from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bsm2_baseline import ScenarioConfig, run_scenario  # noqa: E402
from bsm2_baseline import scenarios as sc  # noqa: E402
from bsm2_baseline.config import InfluentConfig, MeasurementConfig  # noqa: E402
from bsm2_baseline.energy import run_power_simulation  # noqa: E402
from bsm2_baseline.export import _stream_frame  # noqa: E402
from bsm2_baseline.variables import COMPLIANCE_VARIABLES, INDEX  # noqa: E402

ACCENT = "#2f5d3a"
REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"

# Default effluent permit limits (g/m3) for reference lines / compliance scoring.
DEFAULT_LIMITS = {"S_NH": 4.0, "TSS": 30.0, "BOD5": 25.0, "COD": 125.0, "Total_N": 18.0, "TP": 1.0}
UNITS = {"S_NH": "g(N)/m3", "S_NO": "g(N)/m3", "Total_N": "g(N)/m3", "TSS": "g(SS)/m3",
         "COD": "g(COD)/m3", "BOD5": "g(BOD)/m3", "Q": "m3/d", "S_PO4": "g(P)/m3", "TP": "g(P)/m3"}
MEASURABLE = tuple(c for c in COMPLIANCE_VARIABLES if c in INDEX)


# --------------------------------------------------------------------------- helpers

def result_to_effluent_df(result) -> pd.DataFrame:
    """Build a unified effluent DataFrame (true + measured + event) from a bsm2_python run."""
    df = _stream_frame(result.time, result.true_streams["effluent"], result.derived["effluent"])
    df["event"] = result.event_labels
    for key in MEASURABLE:
        df[f"meas_{key}"] = result.streams["effluent"][:, INDEX[key]]
    return df


def qsdsan_to_effluent_df(result) -> pd.DataFrame:
    """Build an effluent DataFrame from a QSDsan canonical result."""
    df = pd.DataFrame({"time_d": result.time, **result.effluent})
    df["event"] = "none"
    return df


def event_spans(df: pd.DataFrame) -> list[tuple[float, float, str]]:
    """Contiguous (start, end, label) spans where an event is active."""
    if "event" not in df.columns:
        return []
    labels = df["event"].to_numpy()
    t = df["time_d"].to_numpy()
    spans, start, cur = [], None, None
    for i, lab in enumerate(labels):
        if lab != "none" and start is None:
            start, cur = t[i], lab
        elif lab == "none" and start is not None:
            spans.append((start, t[i], cur))
            start = None
    if start is not None:
        spans.append((start, t[-1], cur))
    return spans


def _downsample(df: pd.DataFrame, max_points: int = 4000) -> pd.DataFrame:
    """Stride large series so the browser renders smoothly (the 877k-row baseline → ~4k)."""
    if len(df) <= max_points:
        return df
    return df.iloc[:: len(df) // max_points]


def effluent_figure(df, variables, *, show_measured=False, show_limits=True) -> go.Figure:
    fig = go.Figure()
    palette = ["#c0392b", "#2f5d3a", "#2b6cb0", "#b7791f", "#6b46c1", "#319795"]
    spans = event_spans(df)            # detect on full series, then downsample for plotting
    df = _downsample(df)
    for (start, end, lab) in spans:
        fig.add_vrect(x0=start, x1=end, fillcolor="#e8a13a", opacity=0.16, line_width=0,
                      annotation_text=lab, annotation_position="top left",
                      annotation_font_size=10)
    for i, var in enumerate(variables):
        if var not in df.columns:
            continue
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatter(x=df["time_d"], y=df[var], name=f"{var} (true)",
                                 line=dict(color=color, width=1.1)))
        mcol = f"meas_{var}"
        if show_measured and mcol in df.columns:
            fig.add_trace(go.Scatter(x=df["time_d"], y=df[mcol], name=f"{var} (measured)",
                                     line=dict(color=color, width=0.8, dash="dot"), opacity=0.6))
        if show_limits and var in DEFAULT_LIMITS:
            fig.add_hline(y=DEFAULT_LIMITS[var], line=dict(color=color, width=0.8, dash="dash"),
                          annotation_text=f"{var} limit {DEFAULT_LIMITS[var]:g}",
                          annotation_font_size=9, annotation_font_color=color)
    fig.update_layout(height=440, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02),
                      xaxis_title="time [d]", yaxis_title="concentration / flow")
    return fig


def line_figure(df, cols, *, ylab, height=300) -> go.Figure:
    fig = go.Figure()
    df = _downsample(df)
    palette = ["#2f5d3a", "#c0392b", "#2b6cb0", "#b7791f", "#6b46c1"]
    for i, c in enumerate(cols):
        if c in df.columns:
            fig.add_trace(go.Scatter(x=df["time_d"], y=df[c], name=c,
                                     line=dict(color=palette[i % len(palette)], width=1.1)))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=20, b=10), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02), xaxis_title="time [d]",
                      yaxis_title=ylab)
    return fig


def compliance_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Mean / max / %-time-over-limit for each compliance variable present."""
    rows = []
    for var in COMPLIANCE_VARIABLES:
        if var not in df.columns:
            continue
        series = df[var].to_numpy()
        limit = DEFAULT_LIMITS.get(var)
        pct = float(np.mean(series > limit) * 100) if limit else np.nan
        rows.append({"variable": var, "unit": UNITS.get(var, ""), "mean": round(series.mean(), 2),
                     "max": round(series.max(), 2), "limit": limit,
                     "% time > limit": round(pct, 1) if limit else None})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def run_scenario_cached(engine, variant, scenario, duration, timestep, measurement, seed, influent_mode):
    cfg = ScenarioConfig(
        name="ui", engine=engine, variant=variant, scenario=(None if scenario == "baseline" else scenario),
        duration_days=duration, timestep_minutes=timestep,
        measurement=MeasurementConfig(mode=measurement), seed=seed,
        influent=InfluentConfig(mode=influent_mode), eval_days=5,
    )
    if engine == "qsdsan_bsm2":
        from bsm2_baseline.engines.qsdsan_bsm2 import run_qsdsan_scenario
        res = run_qsdsan_scenario(cfg, kind="bsm2p", progress=False)
        return qsdsan_to_effluent_df(res), None, {"engine": "qsdsan_bsm2", "p_balance": res.p_balance}
    res = run_scenario(cfg, progress=False)
    idx = pd.DataFrame({"time_d": res.time, "IQI": res.indices["IQI"], "EQI": res.indices["EQI"],
                        "OCI": res.indices["OCI"]})
    return result_to_effluent_df(res), idx, {"engine": "bsm2_python",
                                             "final": res.final_performance,
                                             "eval_window": res.eval_window}


@st.cache_data(show_spinner=False)
def run_power_cached(variant, duration, timestep, seed):
    cfg = ScenarioConfig(name="ui_power", variant=variant, duration_days=duration,
                         timestep_minutes=timestep, seed=seed, eval_days=14)
    res = run_power_simulation(cfg, progress=False)
    power = pd.DataFrame({"time_d": res.time, **res.power})
    biogas = pd.DataFrame({"time_d": res.time, **res.biogas})
    return power, biogas, res.economics, res.final_performance


@st.cache_data(show_spinner=False)
def list_datasets():
    if not DATA_DIR.exists():
        return []
    return sorted(str(p.parent.relative_to(DATA_DIR)) for p in DATA_DIR.rglob("effluent.parquet"))


@st.cache_data(show_spinner=False)
def load_dataset(rel):
    base = DATA_DIR / rel
    eff = pd.read_parquet(base / "effluent.parquet")
    idx = pd.read_parquet(base / "indices.parquet") if (base / "indices.parquet").exists() else None
    return eff, idx


# --------------------------------------------------------------------------- UI

st.set_page_config(page_title="BSM2 Simulation", page_icon="💧", layout="wide")
st.markdown(
    f"<h2 style='color:{ACCENT};margin-bottom:0'>BSM2 Simulation</h2>"
    "<p style='color:#5b6660;margin-top:2px'>Wastewater-treatment-plant simulation, "
    "compliance-risk scenarios, and plant power use.</p>",
    unsafe_allow_html=True,
)

mode = st.sidebar.radio("Mode", ["Run a scenario", "Plant power use", "Explore a dataset"])
st.sidebar.divider()


def kpi_row(items):
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items, strict=True):
        col.metric(label, value)


if mode == "Run a scenario":
    engine = st.sidebar.selectbox("Engine", ["bsm2_python", "qsdsan_bsm2"],
                                  help="qsdsan_bsm2 adds phosphorus (TP/S_PO4); slower.")
    presets = [p for p in sc.PRESETS if p != "p_upset" or engine == "qsdsan_bsm2"]
    scenario = st.sidebar.selectbox("Scenario", presets)
    variant = st.sidebar.selectbox("Control", ["open_loop", "closed_loop"],
                                   help="open_loop is faster; closed_loop runs the DO controller.")
    measurement = st.sidebar.selectbox("Sensors", ["ideal", "realistic"])
    duration = st.sidebar.slider("Duration [days]", 10, 180, 90, 10)
    timestep = st.sidebar.select_slider("Timestep [min]", [1.0, 5.0, 15.0], value=15.0)
    seed = st.sidebar.number_input("Seed", 0, 9999, 0)
    influent_mode = st.sidebar.selectbox("Influent", ["default", "generate"])

    if engine == "qsdsan_bsm2":
        variant = "open_loop"
        st.sidebar.caption("QSDsan uses its own solver; control variant ignored.")
    if variant == "closed_loop" and timestep > 1.0:
        timestep = 1.0
        st.sidebar.caption("Closed-loop forced to 1-min timestep.")

    run = st.sidebar.button("▶  Run simulation", type="primary", use_container_width=True)
    _events = sc.expand_preset(None if scenario == "baseline" else scenario)
    st.sidebar.caption("Events: " + (", ".join(e.type.value for e in _events) or "none (baseline)"))

    if run:
        with st.spinner(f"Running {scenario} on {engine}…"):
            eff, idx, meta = run_scenario_cached(engine, variant, scenario, float(duration),
                                                 float(timestep), measurement, int(seed), influent_mode)
        st.session_state["run"] = (eff, idx, meta, scenario, engine)

    if "run" in st.session_state:
        eff, idx, meta, scn, eng = st.session_state["run"]
        if meta["engine"] == "bsm2_python":
            fp = meta["final"]
            kpi_row([("EQI", f"{fp['EQI']:.0f}"), ("OCI", f"{fp['OCI']:.0f}"),
                     ("eff S_NH mean", f"{eff['S_NH'].mean():.2f}"),
                     ("eff TSS max", f"{eff['TSS'].max():.0f}"),
                     ("S_NH > 4 g/m³", f"{np.mean(eff['S_NH']>4)*100:.1f}%")])
        else:
            pb = meta["p_balance"]
            kpi_row([("eff TP mean", f"{eff['TP'].mean():.2f}"),
                     ("eff S_PO4 mean", f"{eff['S_PO4'].mean():.2f}"),
                     ("P removed", f"{pb['P_removed_fraction']*100:.0f}%"),
                     ("eff S_NH mean", f"{eff['S_NH'].mean():.2f}")])

        t1, t2, t3 = st.tabs(["Effluent & compliance", "Benchmark indices", "Data"])
        with t1:
            default_vars = [v for v in ["S_NH", "TSS", "Total_N"] if v in eff.columns]
            chosen = st.multiselect("Variables", [c for c in COMPLIANCE_VARIABLES if c in eff.columns],
                                    default=default_vars)
            cc = st.columns(2)
            show_meas = cc[0].toggle("Show measured (sensor) signal",
                                     value=any(f"meas_{v}" in eff.columns for v in chosen))
            show_lim = cc[1].toggle("Show permit limits", value=True)
            st.plotly_chart(effluent_figure(eff, chosen, show_measured=show_meas, show_limits=show_lim),
                            use_container_width=True)
            st.dataframe(compliance_summary(eff), use_container_width=True, hide_index=True)
        with t2:
            if idx is not None:
                st.plotly_chart(line_figure(idx, ["IQI", "EQI", "OCI"], ylab="kg/d (IQI/EQI), index (OCI)",
                                            height=420), use_container_width=True)
            else:
                st.info("Benchmark indices are not produced by the QSDsan engine. "
                        f"Phosphorus balance: {meta.get('p_balance')}")
        with t3:
            st.dataframe(eff.head(2000), use_container_width=True, height=420)
            st.download_button("Download effluent CSV", eff.to_csv(index=False),
                               file_name=f"{scn}_effluent.csv", mime="text/csv")
    else:
        st.info("Pick a scenario in the sidebar and press **Run simulation**.")

elif mode == "Plant power use":
    variant = st.sidebar.selectbox("Control", ["open_loop", "closed_loop"], index=0)
    duration = st.sidebar.slider("Duration [days]", 10, 180, 90, 10)
    timestep = st.sidebar.select_slider("Timestep [min]", [1.0, 15.0], value=15.0)
    seed = st.sidebar.number_input("Seed", 0, 9999, 0)
    if variant == "closed_loop":
        timestep = 1.0
    if st.sidebar.button("▶  Run power simulation", type="primary", use_container_width=True):
        with st.spinner("Running BSM2OLEM energy model…"):
            st.session_state["power"] = run_power_cached(variant, float(duration), float(timestep), int(seed))
    if "power" in st.session_state:
        power, biogas, econ, fp = st.session_state["power"]
        kpi_row([("demand mean", f"{power['electricity_demand_kW'].mean():.0f} kW"),
                 ("CHP elec mean", f"{power['chp_electricity_kW'].mean():.0f} kW"),
                 ("net grid mean", f"{power['net_grid_import_kW'].mean():.0f} kW"),
                 ("cum cash flow", f"€{econ['final_cum_cash_flow_EUR']:.0f}")])
        st.subheader("Electricity")
        st.plotly_chart(line_figure(power, ["electricity_demand_kW", "chp_electricity_kW",
                        "net_grid_import_kW", "aeration_kW"], ylab="kW", height=380),
                        use_container_width=True)
        c = st.columns(2)
        with c[0]:
            st.subheader("Biogas")
            st.plotly_chart(line_figure(biogas, ["biogas_production_Nm3_per_d"], ylab="Nm³/d"),
                            use_container_width=True)
        with c[1]:
            st.subheader("Electricity price")
            st.plotly_chart(line_figure(power, ["electricity_price_EUR_per_MWh"], ylab="€/MWh"),
                            use_container_width=True)
        st.caption("A well-digesting plant runs net-negative on grid import — CHP exports power.")
    else:
        st.info("Press **Run power simulation** to model plant energy use (BSM2OLEM).")

else:  # Explore a dataset
    datasets = list_datasets()
    if not datasets:
        st.warning("No datasets found under `data/`. Run a scenario first, or use one of the "
                   "`scripts/run_*.py` entry points.")
    else:
        _default = next((i for i, d in enumerate(datasets) if d == "bulking_event"), 0)
        rel = st.sidebar.selectbox("Dataset", datasets, index=_default)
        eff, idx = load_dataset(rel)
        st.caption(f"`data/{rel}` — {len(eff):,} timesteps, {eff['time_d'].max():.0f} days")
        kpi_row([("rows", f"{len(eff):,}"),
                 ("eff S_NH mean", f"{eff['S_NH'].mean():.2f}" if "S_NH" in eff else "—"),
                 ("eff TSS max", f"{eff['TSS'].max():.0f}" if "TSS" in eff else "—"),
                 ("span", f"{eff['time_d'].max():.0f} d")])
        chosen = st.multiselect("Variables", [c for c in COMPLIANCE_VARIABLES if c in eff.columns],
                                default=[v for v in ["S_NH", "TSS", "Total_N"] if v in eff.columns])
        show_meas = st.toggle("Show measured (sensor) signal",
                              value=any(f"meas_{v}" in eff.columns for v in chosen))
        st.plotly_chart(effluent_figure(eff, chosen, show_measured=show_meas),
                        use_container_width=True)
        st.dataframe(compliance_summary(eff), use_container_width=True, hide_index=True)
        if idx is not None:
            st.plotly_chart(line_figure(idx, ["IQI", "EQI", "OCI"], ylab="indices"),
                            use_container_width=True)
