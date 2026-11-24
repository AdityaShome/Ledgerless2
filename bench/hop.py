"""Local, explicitly scoped benchmark adapters; no network/LLM latency included."""

import asyncio
from dataclasses import dataclass, field
from threading import Lock

from recovery.crypto import generate_keypair
from recovery.intents import make_intent
from recovery.service import RecoveryService
from recovery.store import Store


@dataclass
class Hop:
    name: str
    mode: str = "ledgerless"
    effects: int = 0
    quarantines: int = 0
    history: dict = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def __post_init__(self):
        priv, _ = generate_keypair()
        self.service = RecoveryService(Store(org_id=self.name), priv, self.name)

    def _effect(self):
        self.effects += 1
        return f"{self.name}:{self.effects}"

    def _execute(self, intent):
        if self.mode == "default_sdk":
            # Request/task identity is all this control baseline preserves.
            with self.lock:
                if intent.intent_id not in self.history:
                    self.history[intent.intent_id] = (
                        intent.chain_id,
                        intent.digest,
                        self._effect(),
                    )
                return "committed"
        state, receipt = self.service.execute_effect(intent, self._effect)
        return "committed" if receipt and receipt.status == "committed" else state

    async def execute(self, intent):
        return await asyncio.to_thread(self._execute, intent)

    async def retry(self, intent):
        return await self.execute(make_intent(intent.chain_id, intent.digest))

    def resolve(self, intent, chain_id=None):
        if self.mode == "default_sdk":
            value = self.history.get(intent.intent_id)
            return {"state": "committed" if value else "unknown"}
        result = self.service.resolve(chain_id or intent.chain_id, intent.intent_id, intent.digest)
        if result["state"] == "quarantine":
            self.quarantines += 1
        return result

    def close(self):
        self.service.store.close()
