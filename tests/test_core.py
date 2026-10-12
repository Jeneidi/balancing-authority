import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forecast import FEATURES, add_features, bootstrap_ci, mape


def test_mape_and_bootstrap_are_deterministic():
    assert round(mape([100, 200], [110, 180]), 6) == 10.0
    assert bootstrap_ci([1, 2, 3], seed=7, draws=20) == bootstrap_ci([1, 2, 3], seed=7, draws=20)


def test_feature_builder_has_no_future_issue_time():
    timestamps = pd.date_range("2025-01-01", periods=200, freq="h", tz="UTC")
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "local_timestamp": timestamps.tz_convert("America/New_York").tz_localize(None),
        "demand": np.arange(200, dtype=float) + 1000,
        "operator_forecast": np.arange(200, dtype=float) + 1000,
    })
    weather = pd.DataFrame({
        "timestamp": timestamps,
        "temperature_forecast_c": np.linspace(10, 20, len(timestamps)),
    })
    result = add_features(frame, weather)
    assert result[FEATURES].notna().all().all()
    assert (result["weather_issue_timestamp"] <= result["timestamp"] - pd.Timedelta(days=1)).all()
    assert (result["issue_timestamp"] <= result["timestamp"] - pd.Timedelta(days=1)).all()


def test_interval_and_metric_inputs_are_numeric():
    assert np.isfinite(mape([1000, 1050], [990, 1070]))
