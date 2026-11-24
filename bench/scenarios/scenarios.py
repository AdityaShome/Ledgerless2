"""Scenario catalogue. A scenario that needs a retry to be visible also drops a response."""

from __future__ import annotations

from dataclasses import replace

from bench.faults import FaultPlan

SCENARIOS: dict[str, FaultPlan] = {
    "F0_clean": FaultPlan(),
    "F1_crash_after_effect": FaultPlan(crash_after_effect=True),
    "F2_receipt_lost": FaultPlan(drop_response=True),
    "F3_duplicate_delivery": FaultPlan(dup_request=True),
    "F4_replica_failover": FaultPlan(drop_response=True, failover=True),
    "F5_replan_on_replay": FaultPlan(drop_response=True, p_replan=0.5),
    "F6_partition_transient": FaultPlan(drop_response=True, partition_resolves=2),
    "F6_partition_permanent": FaultPlan(drop_response=True, partition_resolves=10**6),
    "F7_forged_receipt": FaultPlan(forge_receipt=True),
    "F8_upstream_abort": FaultPlan(abort_upstream=True),
}


def with_replan(name: str, p: float) -> FaultPlan:
    return replace(SCENARIOS[name], p_replan=p)
