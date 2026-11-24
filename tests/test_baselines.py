import pytest

from bench.engine import World, ours_at
from bench.granularity import POLICIES, run_granularity
from bench.scenarios.scenarios import SCENARIOS
from bench.systems import ABLATIONS, BASELINES, LABELS, SYSTEMS, run_system
from recovery.intents import Granularity

SEEDS = range(40)


def tot(system, scenario, depth=3, fanout=1, seeds=SEEDS):
    rs = [run_system(system, scenario, SCENARIOS[scenario], s, depth, fanout) for s in seeds]
    return {
        "dup": sum(r.duplicates for r in rs),
        "done": sum(r.completed for r in rs),
        "q": sum(r.quarantined for r in rs),
        "residual": sum(r.residual for r in rs),
        "aborted": sum(r.aborted for r in rs),
        "n": len(rs),
    }


# ---- Phase 5 acceptance: every baseline and ablation runs under the same harness ----------


@pytest.mark.parametrize("system", sorted(SYSTEMS))
def test_every_system_runs_every_scenario(system):
    for scenario, plan in SCENARIOS.items():
        r = run_system(system, scenario, plan, 3, depth=3, fanout=3)
        assert r.system == system and r.intended == 7  # root + 3 branches x 2 hops


def test_registry_covers_guide_baselines_and_ablations():
    assert set(BASELINES) == {"default_sdk", "request_id", "saga", "temporal_bridge"}
    assert set(BASELINES) | set(ABLATIONS) <= set(SYSTEMS)
    assert "UPPER BOUND" in LABELS["temporal_bridge"]


# ---- Temporal stand-in is the upper bound ---------------------------------------------------


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s.startswith(("F0", "F1", "F2"))
                                      or s[:2] in ("F3", "F4", "F5", "F6")])
def test_temporal_upper_bound_is_correct_without_resolve(scenario):
    t = tot("temporal_bridge", scenario)
    assert t["dup"] == 0 and t["done"] == t["n"]


def test_temporal_costs_extra_control_plane_messages():
    a = run_system("temporal_bridge", "F0", SCENARIOS["F0_clean"], 1)
    b = run_system("default_sdk", "F0", SCENARIOS["F0_clean"], 1)
    assert a.messages > b.messages


# ---- Saga: full view fixes retries but not executor-level duplicates ----------------------


@pytest.mark.parametrize("s", ["F1_crash_after_effect", "F2_receipt_lost", "F4_replica_failover",
                               "F5_replan_on_replay", "F6_partition_transient"])
def test_saga_inspection_prevents_retry_duplicates(s):
    t = tot("saga", s)
    assert t["dup"] == 0 and t["done"] == t["n"]


def test_saga_hops_do_not_dedup_duplicate_delivery():
    assert tot("saga", "F3_duplicate_delivery")["dup"] > 0


def test_saga_gives_up_and_compensates_when_inspection_is_down():
    t = tot("saga", "F6_partition_permanent")
    assert t["done"] == 0 and t["aborted"] == t["n"]
    assert t["residual"] > 0  # the in-doubt effect cannot be undone


# ---- upstream abort exercises COMPENSATE -----------------------------------------------------


@pytest.mark.parametrize("system", ["ours", "saga", "temporal_bridge", "ours_no_resolve"])
def test_systems_with_evidence_clean_up_after_abort(system):
    t = tot(system, "F8_upstream_abort")
    assert t["aborted"] == t["n"] and t["residual"] == 0


@pytest.mark.parametrize("system", ["default_sdk", "request_id", "ours_no_intents"])
def test_systems_without_compensation_leave_effects_standing(system):
    assert tot(system, "F8_upstream_abort")["residual"] > 0


def test_ours_compensation_is_receipt_driven():
    r = run_system("ours", "F8", SCENARIOS["F8_upstream_abort"], 0)
    assert r.compensations == r.intended and r.residual == 0


# ---- ablations -----------------------------------------------------------------------------


def test_no_resolve_quarantines_every_in_doubt_call_but_never_duplicates():
    for s in ("F1_crash_after_effect", "F2_receipt_lost", "F5_replan_on_replay"):
        t = tot("ours_no_resolve", s)
        assert t["dup"] == 0 and t["q"] == t["n"] and t["done"] == 0
    assert tot("ours_no_resolve", "F3_duplicate_delivery")["done"] == SEEDS.stop


def test_no_intents_receipts_only_handles_failover_but_not_replan():
    assert tot("ours_no_intents", "F4_replica_failover")["dup"] == 0
    assert tot("ours_no_intents", "F5_replan_on_replay")["dup"] > 0


def test_digest_only_granularity_decides_replan_dedup():
    f5 = "F5_replan_on_replay"
    assert tot("digest_only_coarse", f5)["dup"] == 0
    assert tot("digest_only_medium", f5)["dup"] == 0
    assert tot("digest_only_fine", f5)["dup"] > 0


@pytest.mark.parametrize("system", ["ours_coarse", "ours"])
def test_resolve_with_coarse_or_medium_digest_has_no_duplicates_under_replan(system):
    assert tot(system, "F5_replan_on_replay")["dup"] == 0


def test_fine_digest_leaks_duplicates_through_redelegation_even_with_resolve():
    """Finding: resolveIntent protects the faulted hop, but when that hop re-delegates
    downstream the call is a replay that may re-plan; a fine digest then misses the dedup."""
    f5 = SCENARIOS["F5_replan_on_replay"]
    dups_at_faulted_hop = 0
    dups_downstream = 0
    for seed in SEEDS:
        w = World(ours_at(Granularity.FINE), f5, seed, 3, 1, "F5")
        w.run()
        for name, hop in w.hops.items():
            d = hop.tool.duplicates()
            if name == w.faults.victim:
                dups_at_faulted_hop += d
            else:
                dups_downstream += d
    assert dups_at_faulted_hop == 0 and dups_downstream > 0


# ---- RQ4: false dedup vs missed dedup ----------------------------------------------------


def rates(policy):
    rs = [run_granularity(policy, s) for s in range(15)]
    legit, replans = sum(r.legit for r in rs), sum(r.replans for r in rs)
    return (
        sum(r.false_dedup for r in rs) / legit,
        sum(r.missed_dedup for r in rs) / replans,
    )


def test_rq4_tradeoff_shape():
    assert set(POLICIES) == {"coarse", "medium_amount", "medium_right", "fine"}
    coarse_f, coarse_m = rates("coarse")
    under_f, under_m = rates("medium_amount")
    right_f, right_m = rates("medium_right")
    fine_f, fine_m = rates("fine")
    assert coarse_f > under_f > 0 and coarse_m == under_m == 0
    assert right_f == 0 and right_m == 0
    assert fine_f == 0 and fine_m == 1.0


# ---- D29: persisted downstream plans close the re-delegation leak -------------------------


def test_persisted_plan_closes_fine_digest_leak():
    f5 = "F5_replan_on_replay"
    assert tot("ours_fine", f5)["dup"] > 0  # weakness stays documented
    for s in ("ours_fine_persist", "ours_medium_persist"):
        t = tot(s, f5)
        assert t["dup"] == 0 and t["done"] == t["n"]


def test_persisted_plan_has_a_measured_cost_and_is_reloaded_from_store():
    r = run_system("ours_fine_persist", "F0", SCENARIOS["F0_clean"], 1)
    assert r.plan_bytes > 0
    assert run_system("ours", "F0", SCENARIOS["F0_clean"], 1).plan_bytes == 0
    from recovery.store import Store

    s = Store()
    first = s.put_plan("c", "h1", {"a": 1})
    assert s.put_plan("c", "h1", {"a": 2}) == first == {"a": 1}  # first write wins
