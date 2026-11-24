"""Quarantine on uncertainty; a policy comparator, not the Agent Mesh product."""

from bench.hop import Hop


class MeshQuarantineHop(Hop):
    def __init__(self, name):
        super().__init__(name, mode="mesh_quarantine_sim")

    async def retry(self, intent):
        self.quarantines += 1
        return "quarantine"

    def resolve(self, intent, chain_id=None):
        self.quarantines += 1
        return {"state": "quarantine"}
