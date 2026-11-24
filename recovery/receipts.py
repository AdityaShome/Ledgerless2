"""Hash-chained, signed effect receipts (guide 3.2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from recovery.crypto import canonical, sha256_hex, sign, verify

STATUSES = ("committed", "tombstone")


@dataclass(frozen=True)
class Receipt:
    intent_id: str
    digest: str
    status: str
    effect_ref: str | None
    prev: str | None
    hash: str
    sig: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Receipt:
        return Receipt(
            intent_id=d["intent_id"],
            digest=d["digest"],
            status=d["status"],
            effect_ref=d.get("effect_ref"),
            prev=d.get("prev"),
            hash=d["hash"],
            sig=d["sig"],
        )


def _body(r: Receipt) -> dict[str, Any]:
    """Receipt minus hash and sig: the bytes the hash covers."""
    return {
        "intent_id": r.intent_id,
        "digest": r.digest,
        "status": r.status,
        "effect_ref": r.effect_ref,
        "prev": r.prev,
    }


def compute_hash(r: Receipt) -> str:
    return sha256_hex(canonical(_body(r)))


def make_receipt(
    priv: Ed25519PrivateKey,
    intent_id: str,
    digest: str,
    status: str,
    effect_ref: str | None,
    prev: str | None,
) -> Receipt:
    if status not in STATUSES:
        raise ValueError(f"bad status {status!r}")
    draft = Receipt(intent_id, digest, status, effect_ref, prev, hash="", sig="")
    h = compute_hash(draft)
    return Receipt(intent_id, digest, status, effect_ref, prev, hash=h, sig=sign(priv, h.encode()))


def verify_receipt(r: Receipt, pub: Ed25519PublicKey) -> bool:
    """True iff the hash matches the body and the signature covers the hash."""
    if r.status not in STATUSES or r.hash != compute_hash(r):
        return False
    return verify(pub, r.hash.encode(), r.sig)


def verify_chain(chain: list[Receipt], pubkeys: list[Ed25519PublicKey]) -> int | None:
    """Verify receipts ordered oldest -> newest, one signer key per receipt.

    Returns None if the chain is valid, else the index of the first bad receipt.
    """
    if len(chain) != len(pubkeys):
        raise ValueError("one public key per receipt required")
    prev_hash: str | None = None
    for i, (r, pub) in enumerate(zip(chain, pubkeys, strict=True)):
        if r.prev != prev_hash or not verify_receipt(r, pub):
            return i
        prev_hash = r.hash
    return None
