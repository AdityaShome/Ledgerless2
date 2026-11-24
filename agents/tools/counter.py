"""Fake side-effecting tool with a ground-truth effect counter."""

from __future__ import annotations

import threading


class EffectCounter:
    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self.count = 0
        self.compensated = 0
        self.log: list[str] = []

    def apply(self, detail: str = "") -> str:
        with self._lock:
            self.count += 1
            self.log.append(detail)
            return f"{self.name}-effect-{self.count}"

    def compensate(self, effect_ref: str) -> str:
        """Undo one application (refund, cancel, ...). Callers guarantee at-most-once."""
        with self._lock:
            self.compensated += 1
            return f"compensated-{effect_ref}"

    @property
    def net(self) -> int:
        """Effects still standing."""
        return self.count - self.compensated
