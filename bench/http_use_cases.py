"""Real HTTP fault matrix; retained upstream simulation covers re-plan/RQ4 sweeps."""

import argparse
import asyncio
import json
from pathlib import Path

from examples.workflow import CASES, FAULTS, run_case


async def run(cases, faults, budget):
    results = []
    for case in cases:
        for fault in faults:
            row = await run_case(case, fault)
            row["recovery_budget_bytes_per_hop"] = budget
            row["within_recovery_budget"] = all(
                m["recovery_bytes"] <= budget for m in row["wire_metrics"].values()
            )
            results.append(row)
            print(
                f"{case:12} {fault:22} {row['status']:12} duplicates={row['duplicate_effects']}",
                flush=True,
            )
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case", choices=(*CASES, "all"), default="all")
    p.add_argument("--fault", choices=(*FAULTS, "all"), default="all")
    p.add_argument("--output", type=Path, default=Path("results/http_use_cases.json"))
    p.add_argument(
        "--recovery-budget-bytes-per-hop",
        type=int,
        default=65536,
        help="Predeclared metadata budget for these tiny fixtures, not a general protocol bound",
    )
    args = p.parse_args()
    rows = asyncio.run(
        run(
            CASES if args.case == "all" else (args.case,),
            FAULTS if args.fault == "all" else (args.fault,),
            args.recovery_budget_bytes_per_hop,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2))
    text = [
        "# Real HTTP use-case validation",
        "",
        "Synthetic effects with idempotent per-organization providers. No live LLMs or real transactions.",
        "",
        f"Predeclared recovery-metadata budget: {args.recovery_budget_bytes_per_hop} bytes per hop.",
        "Bytes are JSON bodies and recovery metadata; transport headers and dashboard polling are excluded.",
        "",
        "| Use case | Fault | Status | Duplicates | Uncompleted | ms | Budget |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    failures = []
    for r in rows:
        expected = (
            "compensated"
            if r["fault"] == "upstream_abort"
            else (
                "quarantine"
                if r["fault"] in ("permanent_partition", "forged_receipt", "changed_action")
                else "completed"
            )
        )
        if r["status"] != expected or r["duplicate_effects"] or r["uncompleted_effects"]:
            failures.append((r["use_case"], r["fault"]))
        text.append(
            f"| {r['use_case']} | {r['fault']} | {r['status']} | {r['duplicate_effects']} | "
            f"{r['uncompleted_effects']} | {r['elapsed_ms']} | {r['within_recovery_budget']} |"
        )
    args.output.with_suffix(".md").write_text("\n".join(text) + "\n")
    if failures:
        raise SystemExit(f"Unexpected outcomes: {failures}")


if __name__ == "__main__":
    main()
