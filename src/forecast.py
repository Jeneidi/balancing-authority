"""Leakage-safe day-ahead demand forecasting and evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor, early_stopping

AUTHORITIES = {
    "FPL": {"name": "Florida Power & Light", "latitude": 28.5, "longitude": -81.4},
    "DUK": {"name": "Duke Energy Carolinas", "latitude": 35.2, "longitude": -80.8},
    "TVA": {"name": "Tennessee Valley Authority", "latitude": 36.2, "longitude": -86.8},
}
EIA_FIELDS = [
    "Balancing Authority",
    "Data Date",
    "Hour Number",
    "Local Time at End of Hour",
    "UTC Time at End of Hour",
    "Demand Forecast (MW)",
    "Demand (MW)",
    "Demand (MW) (Adjusted)",
]
FEATURES = [
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "day_sin",
    "day_cos",
    "demand_lag_24",
    "demand_lag_168",
    "temperature_forecast_c",
]
TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")
VALIDATION_END = pd.Timestamp("2026-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-07-01", tz="UTC")


def mape(actual: Iterable[float], predicted: Iterable[float]) -> float:
    actual_values = np.asarray(list(actual), dtype=float)
    predicted_values = np.asarray(list(predicted), dtype=float)
    denominator = np.maximum(np.abs(actual_values), 1.0)
    return float(np.mean(np.abs(actual_values - predicted_values) / denominator) * 100)


def bootstrap_ci(values: Iterable[float], seed: int = 7, draws: int = 1000) -> tuple[float, float]:
    values_array = np.asarray(list(values), dtype=float)
    rng = np.random.default_rng(seed)
    samples = rng.choice(values_array, size=(draws, len(values_array)), replace=True).mean(axis=1)
    return float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))


def load_eia(raw_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(raw_dir.glob("EIA930_BALANCE_*.csv")):
        frame = pd.read_csv(path, usecols=EIA_FIELDS, low_memory=False)
        frame = frame[frame["Balancing Authority"].isin(AUTHORITIES)].copy()
        frame["timestamp"] = pd.to_datetime(frame["UTC Time at End of Hour"], utc=True)
        frame["local_timestamp"] = pd.to_datetime(frame["Local Time at End of Hour"], errors="coerce")
        raw_demand = pd.to_numeric(frame["Demand (MW)"], errors="coerce")
        adjusted_demand = pd.to_numeric(frame["Demand (MW) (Adjusted)"], errors="coerce")
        frame["demand"] = adjusted_demand.fillna(raw_demand)
        frame["operator_forecast"] = pd.to_numeric(frame["Demand Forecast (MW)"], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "demand", "operator_forecast"])
        frames.append(frame[["Balancing Authority", "timestamp", "local_timestamp", "demand", "operator_forecast"]])
    if not frames:
        raise FileNotFoundError(f"No EIA files found in {raw_dir}")
    result = pd.concat(frames, ignore_index=True).drop_duplicates(["Balancing Authority", "timestamp"])
    return result.sort_values(["Balancing Authority", "timestamp"]).reset_index(drop=True)


def load_weather(raw_dir: Path, authority: str) -> pd.DataFrame:
    payload = json.loads((raw_dir / f"weather_{authority}.json").read_text(encoding="utf-8"))
    hourly = payload["hourly"]
    result = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly["time"], utc=True),
        "temperature_forecast_c": hourly["temperature_2m_previous_day1"],
    })
    return result.dropna().drop_duplicates("timestamp")


def add_features(frame: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_values("timestamp").copy()
    result["hour"] = result["local_timestamp"].dt.hour
    result["day_of_week"] = result["local_timestamp"].dt.dayofweek
    result["month"] = result["local_timestamp"].dt.month
    result["is_weekend"] = (result["day_of_week"] >= 5).astype(int)
    result["day_sin"] = np.sin(2 * np.pi * result["day_of_week"] / 7)
    result["day_cos"] = np.cos(2 * np.pi * result["day_of_week"] / 7)
    result["demand_lag_24"] = result["demand"].shift(24)
    result["demand_lag_168"] = result["demand"].shift(168)
    result = result.merge(weather, on="timestamp", how="left")
    result["issue_timestamp"] = result["timestamp"] - pd.Timedelta(days=1)
    result["weather_issue_timestamp"] = result["issue_timestamp"]
    return result.dropna(subset=FEATURES).reset_index(drop=True)


def holiday_name(day: pd.Timestamp) -> str:
    fixed = {
        (1, 1): "New Year's Day",
        (7, 4): "Independence Day",
        (12, 25): "Christmas Day",
    }
    return fixed.get((day.month, day.day), "")


def train_and_evaluate(frame: pd.DataFrame, authority: str) -> dict:
    train = frame[frame.timestamp < TRAIN_END]
    validation = frame[(frame.timestamp >= TRAIN_END) & (frame.timestamp < VALIDATION_END)]
    test = frame[(frame.timestamp >= VALIDATION_END) & (frame.timestamp < TEST_END)].copy()
    model = LGBMRegressor(
        objective="regression_l2",
        n_estimators=500,
        learning_rate=0.04,
        num_leaves=31,
        min_child_samples=30,
        random_state=7,
        n_jobs=1,
        verbosity=-1,
    )
    model.fit(
        train[FEATURES],
        train["demand"],
        eval_set=[(validation[FEATURES], validation["demand"])],
        callbacks=[early_stopping(30, verbose=False)],
    )
    validation = validation.copy()
    validation["prediction"] = model.predict(validation[FEATURES], num_iteration=model.best_iteration_)
    error_quantiles = np.quantile(validation["demand"] - validation["prediction"], [0.05, 0.95])
    test["prediction"] = model.predict(test[FEATURES], num_iteration=model.best_iteration_)
    test["lower"] = test["prediction"] + error_quantiles[0]
    test["upper"] = test["prediction"] + error_quantiles[1]
    test["last_week"] = test["demand_lag_168"]
    test["day"] = test["timestamp"].dt.strftime("%Y-%m-%d")
    test["holiday"] = test["timestamp"].map(holiday_name)

    day_rows = []
    for day, group in test.groupby("day", sort=True):
        actual = group["demand"].to_numpy()
        model_daily = mape(actual, group["prediction"])
        operator_daily = mape(actual, group["operator_forecast"])
        last_week_daily = mape(actual, group["last_week"])
        day_rows.append({
            "day": day,
            "model_mape": model_daily,
            "operator_mape": operator_daily,
            "last_week_mape": last_week_daily,
            "model_wins": model_daily < operator_daily,
            "holiday": next((value for value in group["holiday"] if value), ""),
            "max_temperature_c": float(group["temperature_forecast_c"].max()),
        })
    days = pd.DataFrame(day_rows)
    heat_threshold = float(days["max_temperature_c"].quantile(0.95))
    days["event"] = np.where(days["holiday"].astype(bool), days["holiday"], np.where(days["max_temperature_c"] >= heat_threshold, "Heat wave", ""))
    ci_low, ci_high = bootstrap_ci(days["model_mape"])
    test_rows = test[["timestamp", "day", "demand", "operator_forecast", "prediction", "lower", "upper"]].copy()
    test_rows["timestamp"] = test_rows["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    worst = days.sort_values("model_mape", ascending=False).head(5).to_dict("records")
    return {
        "authority": authority,
        "display_name": AUTHORITIES[authority]["name"],
        "rows": int(len(test)),
        "days": int(len(days)),
        "best_iteration": int(model.best_iteration_),
        "model_mape": mape(test["demand"], test["prediction"]),
        "operator_mape": mape(test["demand"], test["operator_forecast"]),
        "last_week_mape": mape(test["demand"], test["last_week"]),
        "model_ci_low": ci_low,
        "model_ci_high": ci_high,
        "win_rate": float(days["model_wins"].mean() * 100),
        "coverage_90": float(((test["demand"] >= test["lower"]) & (test["demand"] <= test["upper"])).mean() * 100),
        "interval_lower_error": float(error_quantiles[0]),
        "interval_upper_error": float(error_quantiles[1]),
        "worst_days": worst,
        "daily": days.to_dict("records"),
        "series": test_rows.to_dict("records"),
    }


def build_results(raw_dir: Path, output_path: Path) -> dict:
    eia = load_eia(raw_dir)
    results = []
    for authority in AUTHORITIES:
        rows = eia[eia["Balancing Authority"] == authority].copy()
        enriched = add_features(rows, load_weather(raw_dir, authority))
        results.append(train_and_evaluate(enriched, authority))
    payload = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "train_period": "2024-01-01 to 2025-06-30",
        "validation_period": "2025-07-01 to 2025-12-31",
        "test_period": "2026-01-01 to 2026-06-30",
        "authorities": results,
        "sources": {
            "eia": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/",
            "open_meteo": "https://open-meteo.com/en/docs/previous-runs-api",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
