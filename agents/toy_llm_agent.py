"""Configurable re-planning agent. All non-determinism in the benchmark lives here.

First attempt for a hop is deterministic. On replay, with probability p_replan the agent
re-plans: a new request id and different incidental wording (memo), but the same effect
(tool, target, amount). Otherwise it replays the identical request (same id, same params).
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class HopSpec:
    name: str
    tool: str
    target: str
    amount: int
    children: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedRequest:
    req_id: str
    hop: str
    params: dict  # amount, target, memo


MEMOS = ("please process", "as discussed", "per request", "follow-up", "routine", "asap")


class ToyLLMAgent:
    def __init__(self, rng: random.Random, p_replan: float = 0.0):
        self.rng = rng
        self.p_replan = p_replan
        self.replans = 0
        self.replay_decisions = 0
        self._first: dict[tuple[str, str], PlannedRequest] = {}
        self._n = 0

    def _mint(self, chain_id: str, spec: HopSpec, memo: str) -> PlannedRequest:
        self._n += 1
        return PlannedRequest(
            req_id=f"{chain_id}/{spec.name}/{self._n}",
            hop=spec.name,
            params={"amount": spec.amount, "target": spec.target, "memo": memo},
        )

    def first(self, chain_id: str, spec: HopSpec) -> PlannedRequest:
        """Deterministic first plan for a hop (same request every time it is asked)."""
        key = (chain_id, spec.name)
        if key not in self._first:
            self._first[key] = self._mint(chain_id, spec, MEMOS[0])
        return self._first[key]

    def next(self, chain_id: str, spec: HopSpec) -> PlannedRequest:
        """Plan a delegation: first plan if never sent, otherwise this is a re-execution."""
        if (chain_id, spec.name) not in self._first:
            return self.first(chain_id, spec)
        return self.replay(chain_id, spec)

    def original(self, chain_id: str, spec: HopSpec) -> PlannedRequest:
        """Re-send exactly what was sent before (used when evidence says it committed)."""
        return self._first[(chain_id, spec.name)]

    def replay(self, chain_id: str, spec: HopSpec) -> PlannedRequest:
        """Blind retry: may re-plan into a different but equivalent request."""
        self.replay_decisions += 1
        if self.rng.random() < self.p_replan:
            self.replans += 1
            memo = self.rng.choice(MEMOS[1:])
            return self._mint(chain_id, spec, memo)
        return self.original(chain_id, spec)
