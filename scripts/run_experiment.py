from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from forecast import build_results


if __name__ == "__main__":
    payload = build_results(ROOT / "data" / "raw", ROOT / "site" / "data" / "results.json")
    for result in payload["authorities"]:
        print(
            f"{result['authority']} model_mape={result['model_mape']:.6f} "
            f"operator_mape={result['operator_mape']:.6f} "
            f"last_week_mape={result['last_week_mape']:.6f} "
            f"win_rate={result['win_rate']:.6f} coverage_90={result['coverage_90']:.6f}"
        )
