import random

import pytest

from agents.tools.fake_tools import FakeTool
from agents.toy_llm_agent import HopSpec, ToyLLMAgent
from bench.engine import DEFAULT_SDK, OURS, REQUEST_ID, run_one
from bench.faults import FaultPlan, FaultState
from bench.scenarios.scenarios import SCENARIOS, with_replan

SEEDS = range(60)


def totals(cfg, scenario, plan=None, depth=3, fanout=1, seeds=SEEDS):
    rs = [run_one(cfg, scenario, plan or SCENARIOS[scenario], s, depth, fanout) for s in seeds]
    return {
        "dup": sum(r.duplicates for r in rs),
        "miss": sum(r.missing for r in rs),
        "done": sum(r.completed for r in rs),
        "quarantined": sum(r.quarantined for r in rs),
        "alerts": sum(r.alerts for r in rs),
    }


# ---- Phase 4 acceptance: default SDK duplicates on F1 and F5 ----------------------------


@pytest.mark.parametrize("scenario", ["F1_crash_after_effect", "F5_replan_on_replay"])
def test_default_sdk_shows_duplicates(scenario):
    assert totals(DEFAULT_SDK, scenario)["dup"] > 0


# ---- the system under test ---------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    [
        "F0_clean",
        "F1_crash_after_effect",
        "F2_receipt_lost",
        "F3_duplicate_delivery",
        "F4_replica_failover",
        "F5_replan_on_replay",
        "F6_partition_transient",
    ],
)
@pytest.mark.parametrize("depth,fanout", [(2, 1), (3, 1), (3, 3), (5, 1)])
def test_ours_no_duplicates_no_missing_and_completes(scenario, depth, fanout):
    t = totals(OURS, scenario, depth=depth, fanout=fanout, seeds=range(25))
    assert t["dup"] == 0 and t["miss"] == 0
    assert t["done"] == 25 and t["quarantined"] == 0


def test_permanent_partition_quarantines_but_never_duplicates():
    t = totals(OURS, "F6_partition_permanent")
    assert t["dup"] == 0
    assert t["quarantined"] == len(SEEDS) and t["done"] == 0


def test_forged_receipt_detected_by_ours_accepted_by_baselines():
    t = totals(OURS, "F7_forged_receipt")
    assert t["alerts"] == len(SEEDS) and t["quarantined"] == len(SEEDS)
    assert totals(DEFAULT_SDK, "F7_forged_receipt")["alerts"] == 0
    assert totals(REQUEST_ID, "F7_forged_receipt")["done"] == len(SEEDS)


# ---- baselines fail where the design says they should -------------------------------------


def test_request_id_dedup_survives_crash_and_duplicate_delivery():
    assert totals(REQUEST_ID, "F1_crash_after_effect")["dup"] == 0
    assert totals(REQUEST_ID, "F3_duplicate_delivery")["dup"] == 0


def test_request_id_dedup_fails_on_failover():
    assert totals(REQUEST_ID, "F4_replica_failover")["dup"] > 0


def test_request_id_duplicates_grow_with_p_replan():
    dups = [
        totals(REQUEST_ID, "F5_replan_on_replay", with_replan("F5_replan_on_replay", p))["dup"]
        for p in (0.0, 0.5, 1.0)
    ]
    assert dups[0] == 0 and dups[0] < dups[1] < dups[2]


def test_runs_are_reproducible_and_fault_free_run_is_clean():
    a = run_one(OURS, "F5", SCENARIOS["F5_replan_on_replay"], 7)
    b = run_one(OURS, "F5", SCENARIOS["F5_replan_on_replay"], 7)
    assert a == b
    for cfg in (DEFAULT_SDK, REQUEST_ID, OURS):
        assert totals(cfg, "F0_clean")["dup"] == 0


def test_overhead_is_measured():
    base = run_one(DEFAULT_SDK, "F0_clean", SCENARIOS["F0_clean"], 1)
    ours = run_one(OURS, "F0_clean", SCENARIOS["F0_clean"], 1)
    assert base.recovery_bytes == 0 and ours.recovery_bytes > 0
    assert ours.bytes_total > base.bytes_total


# ---- building blocks -------------------------------------------------------------------------


def test_toy_agent_replan_semantics():
    spec = HopSpec("h", "charge_payment", "t", 5)
    never = ToyLLMAgent(random.Random(0), 0.0)
    first = never.first("c", spec)
    assert never.first("c", spec) is first and never.replay("c", spec) == first
    always = ToyLLMAgent(random.Random(0), 1.0)
    f = always.first("c", spec)
    r = always.replay("c", spec)
    assert r.req_id != f.req_id and r.params["memo"] != f.params["memo"]
    assert (r.params["amount"], r.params["target"]) == (f.params["amount"], f.params["target"])
    assert always.original("c", spec) == f


def test_fake_tool_counts_semantic_duplicates_only():
    t = FakeTool("send_email")
    t.apply("a", 1)
    t.apply("a", 1)
    t.apply("b", 1)
    assert t.duplicates() == 1
    with pytest.raises(ValueError):
        FakeTool("nope")


def test_fault_fires_once_at_victim_only():
    fs = FaultState(FaultPlan(drop_response=True, partition_resolves=2), victim="h1")
    assert not fs.fire("drop_response", "h0")
    assert fs.fire("drop_response", "h1") and not fs.fire("drop_response", "h1")
    assert not fs.fire("dup_request", "h1")  # not in plan
    assert [fs.resolve_blocked("h1") for _ in range(3)] == [True, True, False]
