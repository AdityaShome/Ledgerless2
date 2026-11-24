"""Per-agent recovery logic over a Store: begin / commit / resolve (guide 3.1-3.3)."""

from __future__ import annotations

from functools import wraps
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from recovery.intents import Intent
from recovery.receipts import Receipt, make_receipt
from recovery.store import Store, StoreConflict


def _locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.store.lock:
            return method(self, *args, **kwargs)

    return wrapped


class RecoveryService:
    def __init__(
        self,
        store: Store,
        priv: Ed25519PrivateKey,
        org: str,
        recovering: bool = False,
        provider=None,
    ):
        self.provider = provider
        store.set_org(org)
        self.store = store
        self.priv = priv
        self.org = org
        self.recovering = recovering  # while True, resolveIntent answers "unknown"
        self._in_flight: set[str] = set()

    @_locked
    def begin(self, intent: Intent) -> tuple[str, Receipt | None]:
        """Declare an intent before any side effect.

        Returns ("proceed", None) to execute, ("done", receipt) if the digest already
        committed (dedup), or ("refused", receipt) if the intent was tombstoned.
        """
        if not self.store.binding_matches(intent.chain_id, intent.intent_id, intent.digest):
            raise StoreConflict("intent belongs to another chain or action")
        existing = self.store.get_receipt(intent.intent_id)
        if existing is not None:
            return ("done" if existing.status == "committed" else "refused", existing)
        dup = self.store.committed_for_digest(intent.chain_id, intent.digest)
        if dup is not None:
            if self.store.get_intent(intent.intent_id) is None:
                self.store.record_intent(intent)
            return "done", dup
        if self.recovering:
            return "pending", None
        if intent.intent_id in self._in_flight or any(
            (pending := self.store.get_intent(i)) is not None
            and pending.chain_id == intent.chain_id
            and pending.digest == intent.digest
            for i in self._in_flight
        ):
            return "pending", None
        if self.store.unresolved_for_digest(intent.chain_id, intent.digest) is not None:
            return "pending", None  # crash outcome unresolved; do not blindly repeat
        self.store.record_intent(intent)
        self._in_flight.add(intent.intent_id)
        return "proceed", None

    @_locked
    def commit(self, intent: Intent, effect_ref: str, prev: str | None) -> Receipt:
        """Write the signed committed receipt after the effect ran."""
        receipt = make_receipt(
            self.priv, intent.intent_id, intent.digest, "committed", effect_ref, prev
        )
        try:
            self.store.put_receipt(intent.chain_id, receipt)
        finally:
            self._in_flight.discard(intent.intent_id)
        return receipt

    def abandon(self, intent_id: str) -> None:
        """Effect did not run (error before it); leave the intent declared."""
        self._in_flight.discard(intent_id)

    @_locked
    def resolve(self, chain_id: str, intent_id: str, digest: str) -> dict[str, Any]:
        """recovery/resolveIntent: committed | tombstone | unknown."""
        if not self.store.binding_matches(chain_id, intent_id, digest):
            return {"state": "quarantine", "reason": "task binding mismatch"}
        if intent_id in self._in_flight or self.recovering:
            return {"state": "unknown"}
        existing = self.store.get_receipt(intent_id)
        if existing is not None:
            return {"state": existing.status, "receipt": existing.to_dict()}
        if self.provider is not None:
            try:
                receipt = self.provider.resolve(chain_id, intent_id, digest)
                self.store.put_receipt(chain_id, receipt)
                return {"state": receipt.status, "receipt": receipt.to_dict()}
            except StoreConflict:
                return {"state": "quarantine", "reason": "provider binding or history conflict"}
        r = self.store.get_receipt(intent_id)
        if r is not None:
            return {"state": r.status, "receipt": r.to_dict()}
        dup = self.store.committed_for_digest(chain_id, digest)
        if dup is not None:  # same effect committed under another request id
            return {"state": "committed", "receipt": dup.to_dict()}
        if self.store.unresolved_for_digest(chain_id, digest) is not None:
            return {"state": "unknown"}  # effect may have run before a crash
        tomb = make_receipt(self.priv, intent_id, digest, "tombstone", None, None)
        try:
            self.store.put_receipt(chain_id, tomb)  # durable before answering
        except StoreConflict:
            return {"state": "unknown"}
        return {"state": "tombstone", "receipt": tomb.to_dict()}

    @_locked
    def execute_effect(self, intent, effect):
        """Serialize local callers. External crash atomicity requires tool idempotency."""
        state, receipt = self.begin(intent)
        if state == "proceed":
            ref = effect()
            receipt = self.commit(intent, ref, intent.parent_receipt)
        return state, receipt

    @_locked
    def execute_provider(self, intent, slot):
        """Use a durable idempotent provider; reconcile effects across replica-local stores."""
        if self.provider is None:
            raise ValueError("provider required")
        state, receipt = self.begin(intent)
        if state == "refused" or state == "done":
            return state, receipt
        if state == "pending":
            resolved = self.resolve(intent.chain_id, intent.intent_id, intent.digest)
            if resolved["state"] == "committed":
                return "done", Receipt.from_dict(resolved["receipt"])
            return "pending", None
        try:
            receipt = self.provider.apply(intent, slot)
            self.store.put_receipt(intent.chain_id, receipt)
            return "proceed", receipt
        finally:
            self._in_flight.discard(intent.intent_id)
