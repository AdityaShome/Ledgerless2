"""SagaLLM-style baseline: ONE orchestrator with a full view drives every hop directly.

The orchestrator keeps a central log of acknowledged steps and, when a call times out, inspects
the hop's effect ledger directly (a view no cross-org party has). Hops do no dedup of their own.
On an unrecoverable failure or an upstream abort it compensates the logged steps in reverse.
It cheats on observability, so it is a comparison point, not a deployable design.
"""

from __future__ import annotations

from bench.engine import Hop, RunResult, SystemConfig, World
from bench.faults import FaultPlan

SAGA = SystemConfig("saga", dedup="none")
INSPECT_TRIES = 3


def _dfs(world: World, name: str = "h0") -> list[str]:
    out = [name]
    for child in world.hops[name].spec.children:
        out += _dfs(world, child)
    return out


def _inspect(world: World, hop: Hop) -> str | None:
    """Full-view check of the hop's effect ledger. None if the inspection channel is down."""
    for _ in range(INSPECT_TRIES):
        world.resolves += 1
        world._count(80)
        if world.faults.resolve_blocked(hop.spec.name):
            continue
        world._count(40)
        key = (hop.spec.tool, hop.spec.target, hop.spec.amount)
        return "committed" if hop.tool.effects[key] > 0 else "absent"
    return None


def run_saga(
    scenario: str, plan: FaultPlan, seed: int, depth: int = 3, fanout: int = 1
) -> RunResult:
    w = World(SAGA, plan, seed, depth, fanout, scenario)
    done: list[Hop] = []
    failed = False
    for name in _dfs(w):
        hop = w.hops[name]
        req = w.agent.next(w.chain_id, hop.spec)
        ok = False
        for attempt in range(SAGA.max_retries + 1):
            resp = w._net(hop, req, None, attempt, delegate=False)
            if resp is not None:
                ok = True
                break
            state = _inspect(w, hop)
            if state is None:  # cannot tell: give up on the saga
                break
            if state == "committed":
                ok = True
                break
            req = w.agent.replay(w.chain_id, hop.spec)
        if not ok:
            failed = True
            break
        done.append(hop)

    if failed or plan.abort_upstream:
        w.aborted = True
        for hop in reversed(done):
            w._compensate(hop)
    return w.make_result(not failed)
