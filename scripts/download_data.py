"""Download the verified public inputs for the forecast experiment."""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

EIA_FILES = {
    "2024_Jan_Jun": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jan_Jun.csv",
    "2024_Jul_Dec": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jul_Dec.csv",
    "2025_Jan_Jun": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2025_Jan_Jun.csv",
    "2025_Jul_Dec": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2025_Jul_Dec.csv",
    "2026_Jan_Jun": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2026_Jan_Jun.csv",
}

WEATHER_LOCATIONS = {
    "FPL": (28.5, -81.4),
    "DUK": (35.2, -80.8),
    "TVA": (36.2, -86.8),
}


def download(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1000:
        return
    with requests.get(url, timeout=120, stream=True) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def main() -> None:
    manifest = {"eia": {}, "weather": {}}
    for name, url in EIA_FILES.items():
        target = RAW / f"EIA930_BALANCE_{name}.csv"
        download(url, target)
        manifest["eia"][name] = {"url": url, "bytes": target.stat().st_size}

    for authority, (latitude, longitude) in WEATHER_LOCATIONS.items():
        query = (
            "https://previous-runs-api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}"
            "&start_date=2024-01-01&end_date=2026-06-30"
            "&hourly=temperature_2m_previous_day1&timezone=UTC"
        )
        target = RAW / f"weather_{authority}.json"
        if not target.exists() or target.stat().st_size < 1000:
            response = requests.get(query, timeout=120)
            response.raise_for_status()
            target.write_text(response.text, encoding="utf-8")
        manifest["weather"][authority] = {"url": query, "bytes": target.stat().st_size}

    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
