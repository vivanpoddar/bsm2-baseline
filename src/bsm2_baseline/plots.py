"""Sanity plots for a baseline run, saved to PNG (never blocking).

Plots the compliance-critical effluent signals (ammonia S_NH and total nitrogen) and the
benchmark indices (IQI / EQI / OCI) over time so a run can be eyeballed for physical
plausibility and stability.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: write files, do not open windows
import matplotlib.pyplot as plt  # noqa: E402

from .runner import RunResult  # noqa: E402
from .variables import INDEX  # noqa: E402


def sanity_plots(result: RunResult, *, output_dir: str | Path | None = None) -> list[str]:
    """Write sanity plots for a run. Returns the list of PNG paths."""
    out_root = Path(output_dir or result.config.output_dir) / result.config.name
    out_root.mkdir(parents=True, exist_ok=True)

    t = result.time
    eff = result.streams["effluent"]
    eff_derived = result.derived["effluent"]
    written: list[str] = []

    # 1) Effluent ammonia + total nitrogen.
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    ax1.plot(t, eff[:, INDEX["S_NH"]], color="tab:red", lw=0.7)
    ax1.axhline(4.0, color="k", ls="--", lw=0.8, label="S_NH limit (4 g/m3)")
    ax1.set_ylabel("Effluent S_NH [g(N)/m3]")
    ax1.legend(loc="upper right")
    ax1.set_title(f"{result.config.name}: effluent ammonia & total nitrogen")
    # Total_N is the 2nd derived column (kjeldahlN, totalN, COD, BOD5, X_TSS).
    ax2.plot(t, eff_derived[:, 1], color="tab:blue", lw=0.7)
    ax2.set_ylabel("Effluent Total N [g(N)/m3]")
    ax2.set_xlabel("Time [d]")
    fig.tight_layout()
    p = out_root / "effluent_nitrogen.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    written.append(str(p))

    # 2) Benchmark indices.
    fig, axes = plt.subplots(3, 1, figsize=(11, 7), sharex=True)
    index_colors = (("IQI", "tab:gray"), ("EQI", "tab:green"), ("OCI", "tab:purple"))
    for ax, (key, color) in zip(axes, index_colors, strict=True):
        ax.plot(t, result.indices[key], color=color, lw=0.7)
        ax.set_ylabel(key)
    axes[0].set_title(f"{result.config.name}: benchmark indices")
    axes[-1].set_xlabel("Time [d]")
    fig.tight_layout()
    p = out_root / "indices.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    written.append(str(p))

    return written
