"""python -m bench.runner --repeats 10 [--json results.json]."""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from baselines.mesh_quarantine.agent import MeshQuarantineHop
from baselines.temporal_bridge.agent import TemporalBridgeHop
from bench.hop import Hop
from bench.scenarios.fault_injection import SCENARIOS

FACTORIES = [Hop, lambda name: Hop(name, "default_sdk"), TemporalBridgeHop, MeshQuarantineHop]


async def run(repeats=5):
    results = []
    for scenario in SCENARIOS:
        for factory in FACTORIES:
            for _ in range(repeats):
                chain = [factory(name) for name in ("A", "B", "C")]
                try:
                    results.append(await scenario(chain))
                finally:
                    for hop in chain:
                        hop.close()
    return results


def markdown(results):
    lines = [
        "Local adapter benchmark (simulated faults; no HTTP or LLM latency).",
        "",
        "| Scenario | Adapter | Duplicates | Lost | Wrong task | Quarantine | p50 ms | p95 ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    groups = {}
    for row in results:
        groups.setdefault((row.scenario, row.baseline), []).append(row)
    for (scenario, baseline), rows in groups.items():
        times = sorted(r.recovery_time_ms for r in rows)
        p95 = times[min(len(times) - 1, int((len(times) - 1) * 0.95 + 0.999))]
        lines.append(
            f"| {scenario} | {baseline} | "
            f"{sum(r.duplicate_executions for r in rows)} | "
            f"{sum(r.lost_effects for r in rows)} | "
            f"{sum(r.wrong_task_recoveries for r in rows)} | "
            f"{statistics.mean(r.quarantine_rate for r in rows):.0%} | "
            f"{statistics.median(times):.3f} | {p95:.3f} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    results = asyncio.run(run(args.repeats))
    print(markdown(results))
    if args.json:
        args.json.write_text(json.dumps([r.to_dict() for r in results], indent=2))
    if any(not r.passed for r in results if r.baseline == "ledgerless"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
