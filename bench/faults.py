"""Fault plans F1-F7 and per-run fault state. Each fault fires once at a victim hop."""

from __future__ import annotations

from dataclasses import dataclass, field


class Crash(Exception):
    """Hop crashed after its effect committed, before any response was sent."""


@dataclass(frozen=True)
class FaultPlan:
    crash_after_effect: bool = False  # F1
    drop_response: bool = False  # F2 (receipt/response lost)
    dup_request: bool = False  # F3
    failover: bool = False  # F4: retries land on the other replica
    forge_receipt: bool = False  # F7
    partition_resolves: int = 0  # F6: first N resolveIntent calls unreachable
    p_replan: float = 0.0  # F5 knob
    abort_upstream: bool = False  # F8: root aborts after downstream effects committed


@dataclass
class FaultState:
    plan: FaultPlan
    victim: str
    fired: set[str] = field(default_factory=set)
    resolve_blocks_left: int = 0

    def __post_init__(self) -> None:
        self.resolve_blocks_left = self.plan.partition_resolves

    def fire(self, kind: str, hop: str) -> bool:
        if hop != self.victim or kind in self.fired or not getattr(self.plan, kind):
            return False
        self.fired.add(kind)
        return True

    def resolve_blocked(self, hop: str) -> bool:
        if hop == self.victim and self.resolve_blocks_left > 0:
            self.resolve_blocks_left -= 1
            return True
        return False
