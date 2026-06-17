"""Synthetic influent generator: shape, validation vs published BSM2, realizations."""

from __future__ import annotations

import numpy as np
import pytest

from bsm2_baseline.influent import generate

# ASM1 indices within the 21-component block (col 0 of the output is time).
SI, SS, XI, XS, XBH, SNH, SND, XND, TSS, Q, TEMP = 0, 1, 2, 3, 4, 9, 10, 11, 13, 14, 15

# Published BSM2 influent characteristics (flow-weighted means).
TABLE11 = {SI: 27.21, SS: 58.15, XI: 92.46, XS: 363.77, XBH: 50.66,
           SNH: 23.86, SND: 5.64, XND: 16.12, TSS: 380.17}


@pytest.fixture(scope="module")
def year():
    return generate(365.0, seed=0, weather="rain", dt=1 / 96)


def test_shape_and_finite(year):
    assert year.ndim == 2 and year.shape[1] == 22
    assert np.all(np.isfinite(year))
    assert np.all(year[:, 1 + Q] > 0)             # positive flow
    assert np.all(year[:, 1 + SNH] >= 0)


def test_validates_against_published_means(year):
    comp = year[:, 1:]
    q = comp[:, Q]
    for idx, target in TABLE11.items():
        fw = float(np.sum(comp[:, idx] * q) / np.sum(q))
        assert abs(fw - target) / target < 0.15, f"component {idx}: {fw:.2f} vs {target}"
    # mean flow and temperature
    assert abs(q.mean() - 20668.0) / 20668.0 < 0.03
    t_fw = float(np.sum(comp[:, TEMP] * q) / np.sum(q))
    assert abs(t_fw - 14.86) < 1.0


def test_temperature_seasonality(year):
    temp = year[:, 1 + TEMP]
    assert 8.0 < temp.min() < 12.0
    assert 18.0 < temp.max() < 22.0


def test_realizations_differ_but_deterministic():
    a = generate(60.0, seed=0, weather="rain", n_realizations=3, dt=1 / 48)
    assert a.shape[0] == 3
    # different realizations differ (rain seed offset)
    assert not np.array_equal(a[0], a[1])
    # same seed reproduces exactly
    b = generate(60.0, seed=0, weather="rain", n_realizations=3, dt=1 / 48)
    assert np.array_equal(a, b)


def test_weather_regimes():
    dry = generate(120.0, seed=1, weather="dry", dt=1 / 48)
    storm = generate(120.0, seed=1, weather="storm", dt=1 / 48)
    # storm produces larger peak flow than dry
    assert storm[:, 1 + Q].max() > dry[:, 1 + Q].max()
