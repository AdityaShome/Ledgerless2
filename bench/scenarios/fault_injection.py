"""Repeatable local fault scenarios. Assertions are evaluated by the runner/tests.

Baseline violations are measurements, not exceptions; they must remain visible.
"""

import asyncio
import time
from dataclasses import asdict, dataclass

from recovery.intents import make_intent


@dataclass
class ScenarioResult:
    scenario: str
    baseline: str
    duplicate_executions: int
    lost_effects: int
    wrong_task_recoveries: int
    recovery_time_ms: float
    quarantine_rate: float
    passed: bool

    def to_dict(self):
        return asdict(self)


def result(name, chain, started, expected, wrong=0, uncertain=False):
    effects = sum(h.effects for h in chain)
    quarantines = sum(h.quarantines for h in chain)
    duplicates = sum(max(0, h.effects - 1) for h in chain)
    lost = max(0, expected - effects)
    return ScenarioResult(
        name,
        chain[0].mode,
        duplicates,
        lost,
        wrong,
        (time.perf_counter() - started) * 1000,
        quarantines / max(1, len(chain)),
        duplicates == 0 and wrong == 0 and (lost == 0 or (uncertain and quarantines > 0)),
    )


async def duplicate_execution(chain):
    start = time.perf_counter()
    for h in chain:
        intent = make_intent("duplicate", "work")
        await asyncio.gather(h.execute(intent), h.execute(intent))
    return result("duplicate_execution", chain, start, len(chain))


async def lost_event(chain):
    # Commit, then suppress the response. Re-plan with a fresh request id.
    start = time.perf_counter()
    for h in chain:
        intent = make_intent("lost-response", "work")
        await h.execute(intent)
        await h.retry(intent)
    return result("lost_event", chain, start, len(chain))


async def lost_request(chain):
    # First request is dropped before delivery; a fresh attempt is delivered.
    start = time.perf_counter()
    for h in chain:
        intent = make_intent("lost-request", "work")
        await h.retry(intent)
    return result("lost_request", chain, start, len(chain), uncertain=True)


async def wrong_task_recovery(chain):
    start, wrong = time.perf_counter(), 0
    for h in chain:
        intent = make_intent("right-chain", "work")
        await h.execute(intent)
        response = h.resolve(intent, "foreign-chain")
        wrong += response["state"] in ("committed", "tombstone")
    return result("wrong_task_recovery", chain, start, len(chain), wrong)


async def recovery_time(chain):
    # Time only the recovery path after the injected lost acknowledgement.
    intents = [make_intent("timing", "work") for _ in chain]
    for h, intent in zip(chain, intents, strict=True):
        await h.execute(intent)
    start = time.perf_counter()
    for h, intent in zip(chain, intents, strict=True):
        h.resolve(intent)
    return result("recovery_time", chain, start, len(chain))


SCENARIOS = [duplicate_execution, lost_event, lost_request, wrong_task_recovery, recovery_time]
