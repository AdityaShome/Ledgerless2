"""Fake side-effecting tools with ground-truth effect counters.

An effect's identity is its semantic key (tool, target, amount); incidental fields such as a
memo never change which real-world effect happened.
"""

from __future__ import annotations

from collections import Counter

TOOL_KINDS = ("send_email", "charge_payment", "create_ticket", "book_slot")

SemanticKey = tuple[str, str, int]


class FakeTool:
    def __init__(self, kind: str):
        if kind not in TOOL_KINDS:
            raise ValueError(kind)
        self.kind = kind
        self.effects: Counter[SemanticKey] = Counter()  # gross applications
        self.compensated: Counter[SemanticKey] = Counter()

    def apply(self, target: str, amount: int) -> str:
        """Perform the effect. Returns an opaque external reference."""
        self.effects[(self.kind, target, amount)] += 1
        return f"{self.kind}:{sum(self.effects.values())}"

    def compensate(self, target: str, amount: int) -> None:
        """Undo one application of the effect (refund, cancel, ...)."""
        self.compensated[(self.kind, target, amount)] += 1

    def residual(self) -> int:
        """Effects still standing after compensation."""
        return sum(max(0, n - self.compensated[k]) for k, n in self.effects.items())

    def duplicates(self) -> int:
        return sum(n - 1 for n in self.effects.values() if n > 1)
