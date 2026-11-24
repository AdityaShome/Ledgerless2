"""Phase 6 experiment runner. Writes aggregated CSVs plus a MANIFEST with provenance.

    python -m bench.run grid     # systems x scenarios x depth x fanout, N seeds each
    python -m bench.run sweep    # C1: duplicates vs p_replan
    python -m bench.run rq4      # granularity trade-off
    python -m bench.run all

Result files are only ever produced by this script (never edited by hand). Each run is fully
determined by (system, scenario, depth, fanout, seed); seeds are 0..N-1.
"""

from __future__ import annotations

import csv
import json
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bench.granularity import POLICIES, run_granularity
from bench.scenarios.scenarios import SCENARIOS, with_replan
from bench.systems import SYSTEMS, run_system

RESULTS = Path(__file__).resolve().parent.parent / "results"
SEEDS = 500
DEPTHS = (2, 3, 5)
FANOUTS = (1, 3)
SWEEP_P = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
SWEEP_SYSTEMS = ("default_sdk", "request_id", "ours", "ours_fine", "ours_fine_persist",
                 "temporal_bridge")
RQ4_SEEDS = 100
NO_RECEIPTS = ("default_sdk", "saga")  # systems with no receipts to forge

GRID_FIELDS = [
    "system", "scenario", "depth", "fanout", "n", "dup_runs", "dup_total", "missing_runs",
    "lost_runs", "completed", "quarantined", "alert_runs", "forged_accepted", "aborted",
    "residual_runs", "msgs_mean", "msgs_p50", "msgs_p95", "bytes_mean", "recovery_bytes_mean",
    "plan_bytes_mean", "resolves_mean",
]


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def aggregate(system: str, scenario: str, plan, depth: int, fanout: int, seeds: int) -> dict:
    rs = [run_system(system, scenario, plan, s, depth, fanout) for s in range(seeds)]
    msgs = [r.messages for r in rs]
    forgeable = scenario.startswith("F7") and system not in NO_RECEIPTS
    return {
        "system": system, "scenario": scenario, "depth": depth, "fanout": fanout, "n": len(rs),
        "dup_runs": sum(r.duplicates > 0 for r in rs),
        "dup_total": sum(r.duplicates for r in rs),
        "missing_runs": sum(r.missing > 0 for r in rs),
        # lost = an intended effect never happened AND the system did not flag the chain
        "lost_runs": sum(r.missing > 0 and not r.quarantined and not r.aborted for r in rs),
        "completed": sum(r.completed for r in rs),
        "quarantined": sum(r.quarantined for r in rs),
        "alert_runs": sum(r.alerts > 0 for r in rs),
        "forged_accepted": sum(r.alerts == 0 for r in rs) if forgeable else "",
        "aborted": sum(r.aborted for r in rs),
        "residual_runs": sum(r.residual > 0 for r in rs),
        "msgs_mean": round(statistics.fmean(msgs), 3),
        "msgs_p50": pct(msgs, 0.5), "msgs_p95": pct(msgs, 0.95),
        "bytes_mean": round(statistics.fmean(r.bytes_total for r in rs), 1),
        "recovery_bytes_mean": round(statistics.fmean(r.recovery_bytes for r in rs), 1),
        "plan_bytes_mean": round(statistics.fmean(r.plan_bytes for r in rs), 1),
        "resolves_mean": round(statistics.fmean(r.resolves for r in rs), 3),
    }


def _grid_cell(args):
    return aggregate(*args)


def _sweep_cell(args):
    system, scenario, p, seeds = args
    row = aggregate(system, scenario, with_replan(scenario, p), 3, 1, seeds)
    return dict(row, p_replan=p)


def _write(name: str, fields: list[str], rows: list[dict]) -> None:
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _manifest(name: str, config: dict, started: float) -> None:
    path = RESULTS / "MANIFEST.json"
    m = json.loads(path.read_text()) if path.exists() else {}
    m[name] = {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "bench", "recovery", "agents",
                               "baselines")),
        "config": config,
        "seconds": round(time.time() - started, 1),
    }
    path.write_text(json.dumps(m, indent=2, sort_keys=True))


def run_grid() -> None:
    t = time.time()
    cells = [(s, sc, plan, d, f, SEEDS) for s in SYSTEMS for sc, plan in SCENARIOS.items()
             for d in DEPTHS for f in FANOUTS]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(_grid_cell, cells, chunksize=4))
    _write("grid.csv", GRID_FIELDS, rows)
    _manifest("grid.csv", {"systems": sorted(SYSTEMS), "scenarios": sorted(SCENARIOS),
                           "depths": DEPTHS, "fanouts": FANOUTS, "seeds": f"0..{SEEDS - 1}"}, t)


def run_sweep() -> None:
    t = time.time()
    cells = [(s, "F5_replan_on_replay", p, SEEDS) for s in SWEEP_SYSTEMS for p in SWEEP_P]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(_sweep_cell, cells))
    _write("c1_replan_sweep.csv", GRID_FIELDS + ["p_replan"], rows)
    _manifest("c1_replan_sweep.csv", {"systems": SWEEP_SYSTEMS, "p_replan": SWEEP_P,
                                      "scenario": "F5_replan_on_replay", "depth": 3, "fanout": 1,
                                      "seeds": f"0..{SEEDS - 1}"}, t)


def run_rq4() -> None:
    t = time.time()
    rows = []
    for name in POLICIES:
        rs = [run_granularity(name, s) for s in range(RQ4_SEEDS)]
        legit, replans = sum(r.legit for r in rs), sum(r.replans for r in rs)
        rows.append({
            "policy": name, "legit": legit, "false_dedup": sum(r.false_dedup for r in rs),
            "false_dedup_rate": round(sum(r.false_dedup for r in rs) / legit, 4),
            "replans": replans, "missed_dedup": sum(r.missed_dedup for r in rs),
            "missed_dedup_rate": round(sum(r.missed_dedup for r in rs) / replans, 4),
        })
    _write("rq4_granularity.csv", list(rows[0]), rows)
    _manifest("rq4_granularity.csv", {"policies": list(POLICIES), "seeds": f"0..{RQ4_SEEDS - 1}",
                                      "n_effects": 200, "p_replan": 0.5}, t)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    for key, fn in (("grid", run_grid), ("sweep", run_sweep), ("rq4", run_rq4)):
        if what in (key, "all"):
            fn()
