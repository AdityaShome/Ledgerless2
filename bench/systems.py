"""Registry of every system and ablation, all runnable through one harness call."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from baselines.saga_compensation import run_saga
from bench.engine import (
    DEFAULT_SDK,
    NO_INTENTS,
    NO_RESOLVE,
    OURS,
    REQUEST_ID,
    TEMPORAL,
    RunResult,
    SystemConfig,
    digest_only,
    ours_at,
    ours_persist,
    run_one,
)
from bench.faults import FaultPlan
from recovery.intents import Granularity

Runner = Callable[[str, FaultPlan, int, int, int], RunResult]


def _config_runner(cfg: SystemConfig) -> Runner:
    def run(scenario: str, plan: FaultPlan, seed: int, depth: int = 3, fanout: int = 1):
        return run_one(cfg, scenario, plan, seed, depth, fanout)

    return run


_CONFIGS = [DEFAULT_SDK, REQUEST_ID, TEMPORAL, OURS, NO_INTENTS, NO_RESOLVE]
_CONFIGS += [ours_at(g) for g in Granularity if g is not Granularity.MEDIUM]
_CONFIGS += [digest_only(g) for g in Granularity]
_CONFIGS += [ours_persist(Granularity.MEDIUM), ours_persist(Granularity.FINE)]

SYSTEMS: dict[str, Runner] = {c.name: _config_runner(c) for c in _CONFIGS}
SYSTEMS["saga"] = partial(run_saga)

BASELINES = ("default_sdk", "request_id", "saga", "temporal_bridge")
ABLATIONS = (
    "ours_no_intents",
    "ours_no_resolve",
    "ours_coarse",
    "ours",
    "ours_fine",
    "digest_only_coarse",
    "digest_only_medium",
    "digest_only_fine",
    "ours_medium_persist",
    "ours_fine_persist",
)

LABELS = {
    "temporal_bridge": "Temporal bridge (UPPER BOUND: assumes one control plane)",
    "saga": "Saga (single orchestrator with full view)",
    "default_sdk": "Default A2A SDK (retry)",
    "request_id": "Request-ID idempotency",
    "ours_fine_persist": "Ours, fine digest + persisted plans (D29)",
    "ours_medium_persist": "Ours, medium digest + persisted plans (D29)",
    "ours": "Ours (intents + receipts + resolveIntent)",
}


def run_system(
    name: str, scenario: str, plan: FaultPlan, seed: int, depth: int = 3, fanout: int = 1
) -> RunResult:
    return SYSTEMS[name](scenario, plan, seed, depth, fanout)
