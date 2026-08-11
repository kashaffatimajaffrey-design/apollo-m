"""
Build the complete Real Reddit dataset in one command.

Runs the whole chain so the live corpus reaches every consumer rather than
stopping at a chart:

    score_real_reddit.py    toxicity for each collected comment
    run_real_pipeline.py    CHI, instability, clusters, GNN risk, actions
    gen_forecasts.py --real TFT five-day forecast on the real daily series
    export_real_reddit.py   small artifacts the hosted dashboard reads

Outputs land in outputs/real/, leaving the benchmark untouched, so the dashboard
can offer both and neither overwrites the other.

    python build_real_dataset.py [--skip-score] [--skip-forecast]

--skip-score reuses existing per-comment scores, which is the slow step; useful
when only the layers above the micro layer have changed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def step(name: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 68}\n>>> {name}\n{'=' * 68}", flush=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, *cmd], cwd=ROOT)
    ok = r.returncode == 0
    print(f"<<< {name}: {'ok' if ok else 'FAILED'} ({time.time() - t0:.0f}s)", flush=True)
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-score", action="store_true")
    ap.add_argument("--skip-forecast", action="store_true")
    a = ap.parse_args()

    if not a.skip_score:
        if not step("scoring real comments", ["score_real_reddit.py"]):
            sys.exit("scoring failed — stopping before the layers that depend on it")

    if not step("meso / clusters / actions", ["run_real_pipeline.py"]):
        sys.exit("pipeline failed")

    if not a.skip_forecast:
        # A forecast failure is not fatal: the rest of the dataset is still
        # usable and the dashboard falls back to the benchmark forecast.
        step("TFT forecast", ["gen_forecasts.py", "--real"])

    step("dashboard artifacts", ["export_real_reddit.py"])

    print("\n" + "=" * 68)
    print("Real dataset built. Remaining:")
    print("  python database/db_setup.py     (load into PostgreSQL)")
    print("  git add outputs/real && git commit && git push")
    print("=" * 68)


if __name__ == "__main__":
    main()
