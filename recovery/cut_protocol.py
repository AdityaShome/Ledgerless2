"""Authenticated cut gathering and conservative reconciliation.

A reconciled frontier is an observation, not permission to replay external effects.
Peers sign their own counters; third-party dependencies must be covered by their owner.
"""

import asyncio
from dataclasses import asdict, dataclass, field

from recovery.checkpoint import Checkpoint, dominant_cut, verify_checkpoint
from recovery.receipts import Receipt, verify_receipt


@dataclass(frozen=True)
class CutRequest:
    chain_id: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CutResponse:
    checkpoint: Checkpoint

    def to_dict(self):
        return {"checkpoint": self.checkpoint.to_dict()}

    @classmethod
    def from_dict(cls, data):
        return cls(Checkpoint.from_dict(data["checkpoint"]))


@dataclass
class ReconcileResult:
    dominant_cut: dict[str, int]
    missing_at: list[str]
    conflicts: list[str]
    # Certifies predecessor closure of effect receipts only, never arbitrary task state.
    causally_verified: bool = False
    accepted: dict[str, Checkpoint] = field(default_factory=dict)


async def gather_cut(peers, chain_id, http):
    from recovery.rpc import query_cut_remote

    results = await asyncio.gather(
        *(query_cut_remote(url, chain_id, http) for url in peers), return_exceptions=True
    )
    checkpoints = {}
    for url, cp in zip(peers, results, strict=True):
        if isinstance(cp, BaseException):
            raise RuntimeError(f"cut query failed: {url}") from cp  # noqa: TRY004
        if cp.org_id in checkpoints:
            raise ValueError(f"duplicate organization: {cp.org_id}")
        checkpoints[cp.org_id] = cp
    return checkpoints


def reconcile_cut(local_store, peer_checkpoints, pub_keys):
    accepted, conflicts = {}, []
    scopes = {cp.chain_id for cp in peer_checkpoints.values()}
    if len(scopes) > 1:
        return ReconcileResult({}, [], ["mixed checkpoint chain scopes"])
    with local_store.lock:
        for org, cp in peer_checkpoints.items():
            key = pub_keys.get(org)
            if cp.org_id != org or key is None or not verify_checkpoint(key, cp):
                conflicts.append(f"{org}: invalid signer or signature")
                continue
            old = local_store.peer_checkpoint(org, cp.chain_id)
            if old and (
                cp.epoch < old.epoch
                or (cp.epoch == old.epoch and cp != old)
                or any(cp.cut.get(k, 0) < v for k, v in old.cut.items())
            ):
                conflicts.append(f"{org}: stale or conflicting checkpoint")
                continue
            if (
                old
                and cp.cut[org] == old.cut[org]
                and old.state_digest
                and cp.state_digest != old.state_digest
            ):
                conflicts.append(f"{org}: divergent state at the same version")
                continue
            if old:
                prior_receipts = {r["hash"] for r in old.receipts}
                if not prior_receipts.issubset({r.get("hash") for r in cp.receipts}):
                    conflicts.append(f"{org}: committed evidence disappeared")
                    continue
            try:
                valid_receipts = all(verify_receipt(Receipt.from_dict(r), key) for r in cp.receipts)
            except (KeyError, TypeError, ValueError):
                valid_receipts = False
            if not valid_receipts:
                conflicts.append(f"{org}: invalid receipt manifest")
                continue
            accepted[org] = cp
        frontier = dominant_cut(list(accepted.values()))
        missing = set(pub_keys) - set(accepted)
        for org, version in frontier.items():
            owner = accepted.get(org)
            if owner is None or owner.cut[org] < version:
                missing.add(org)
        receipt_hashes = {
            r["hash"] for cp in accepted.values() for r in cp.receipts if r["status"] == "committed"
        }
        for org, cp in accepted.items():
            for receipt in cp.receipts:
                if receipt["prev"] and receipt["prev"] not in receipt_hashes:
                    missing.add(f"receipt:{receipt['prev']}")
        if not conflicts and not missing:
            for cp in accepted.values():
                local_store.remember_checkpoint(cp)
    return ReconcileResult(
        frontier,
        sorted(missing),
        conflicts,
        causally_verified=bool(receipt_hashes) and not conflicts and not missing,
        accepted=accepted,
    )
