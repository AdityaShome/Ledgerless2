"""In-process workflow-history simulation, NOT Temporal or its crash guarantees."""

import asyncio
import threading

from bench.hop import Hop


class TemporalBridgeHop(Hop):
    def __init__(self, name):
        super().__init__(name, mode="temporal_bridge_sim")
        self.completed = threading.Event()

    def _execute(self, intent):
        with self.lock:
            key = (intent.chain_id, intent.digest)
            if key not in self.history:
                self.history[key] = self._effect()
            self.completed.set()
            return "committed"

    async def execute(self, intent):
        return await asyncio.to_thread(self._execute, intent)

    def resolve(self, intent, chain_id=None):
        if chain_id is not None and chain_id != intent.chain_id:
            return {"state": "quarantine"}
        return {
            "state": "committed"
            if self.completed.is_set() and (intent.chain_id, intent.digest) in self.history
            else "unknown"
        }
