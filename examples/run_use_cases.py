"""python -m examples.run_use_cases --case all --fault lost_response --output runs.json"""

import argparse
import asyncio
import json
from pathlib import Path

from examples.workflow import CASES, FAULTS, run_case


async def run(args):
    cases = CASES if args.case == "all" else (args.case,)
    rows = [await run_case(case, args.fault) for case in cases]
    print("| Use case | Fault | Status | Duplicate effects | Uncompleted | ms |")
    print("|---|---|---|---:|---:|---:|")
    for r in rows:
        print(
            f"| {r['use_case']} | {r['fault']} | {r['status']} | "
            f"{r['duplicate_effects']} | {r['uncompleted_effects']} | {r['elapsed_ms']} |"
        )
    if args.output:
        args.output.write_text(json.dumps(rows, indent=2))
    expected = (
        "compensated"
        if args.fault == "upstream_abort"
        else (
            "quarantine"
            if args.fault in ("permanent_partition", "forged_receipt", "changed_action")
            else "completed"
        )
    )
    if any(r["status"] != expected or r["duplicate_effects"] for r in rows):
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case", choices=(*CASES, "all"), default="all")
    p.add_argument("--fault", choices=FAULTS, default="clean")
    p.add_argument("--output", type=Path)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
