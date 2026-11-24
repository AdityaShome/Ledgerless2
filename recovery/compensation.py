"""Receipt-driven compensation of an aborted chain (the COMPENSATE row of guide 3.4).

Each hop decides for itself, from its own signed receipts, whether to undo an effect. The
compensation is itself an intent plus a signed receipt linked to the original, so it is
idempotent (deterministic intent id and digest) and visible to cut reconciliation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from recovery.crypto import canonical, sha256_hex
from recovery.decide import Action, Evidence, decide
from recovery.intents import make_intent
from recovery.receipts import Receipt, verify_receipt
from recovery.service import RecoveryService

OK_STATUSES = ("compensated", "already_compensated")


def compensation_digest(org: str, original_hash: str) -> str:
    return sha256_hex(
        canonical({"action_type": "compensate", "target": org, "original": original_hash})
    )


def compensation_intent_id(original_hash: str) -> str:
    return "compensate-" + original_hash


def _refuse(entry: dict[str, Any], reason: str, alert: bool = False) -> dict[str, Any]:
    return {**entry, "status": "quarantine", "reason": reason, "alert": alert}


def compensate_local(
    service: RecoveryService,
    chain_id: str,
    undo: Callable[[Receipt], str] | None,
) -> list[dict[str, Any]]:
    """Compensate every committed effect this hop holds evidence for, newest first.

    `undo(original)` performs the external compensation and returns its reference; None
    means the tool cannot compensate. Nothing is declared in that case, so a later retry
    with a capable tool is not blocked by an in-doubt intent.
    """
    store, pub = service.store, service.priv.public_key()
    committed = [r for _, r in store.receipts_for_chain(chain_id) if r.status == "committed"]
    own = {compensation_digest(service.org, r.hash) for r in committed}
    results: list[dict[str, Any]] = []

    # An intent with no receipt may have run before a crash; that is not ours to guess.
    for pending in store.unresolved_intents(chain_id):
        if pending.digest not in own and store.committed_for_digest(chain_id, pending.digest):
            continue  # re-planned duplicate that deduplicated onto a committed receipt
        results.append(
            _refuse(
                {"intent_id": pending.intent_id, "action": Action.RESOLVE.value},
                "intent declared without a receipt; effect may have run",
            )
        )

    for original in reversed([r for r in committed if r.digest not in own]):
        evidence = Evidence(
            receipt=original,
            signature_valid=verify_receipt(original, pub),
            intent_declared=True,
            upstream_aborted=True,
        )
        action = decide(evidence)
        entry = {"original": original.hash, "action": action.value}
        if action is not Action.COMPENSATE:
            results.append(_refuse(entry, action.value, alert=action is Action.QUARANTINE_ALERT))
            continue
        if undo is None:
            results.append(_refuse(entry, "compensation unsupported by this tool"))
            continue
        intent = make_intent(
            chain_id,
            compensation_digest(service.org, original.hash),
            original.hash,
            intent_id=compensation_intent_id(original.hash),
        )
        try:
            state, receipt = service.execute_effect(intent, lambda o=original: undo(o))
        except Exception as exc:  # noqa: BLE001 - report the failure instead of a 500
            service.abandon(intent.intent_id)
            results.append(_refuse(entry, f"compensation failed: {type(exc).__name__}"))
            continue
        if receipt is None:
            results.append(_refuse(entry, "compensation outcome unresolved"))
            continue
        status = "compensated" if state == "proceed" else "already_compensated"
        results.append({**entry, "status": status, "receipt": receipt.to_dict()})
    return results


def compensations_ok(entries: list[dict[str, Any]]) -> bool:
    return all(e.get("status") in OK_STATUSES for e in entries)


def verify_compensations(report: dict[str, Any], chain_id: str, org: str, pub) -> bool:
    """Check a peer's report: right org and chain, and every claimed receipt is genuine,
    signed by the pinned key, bound to its original and linked to it by `prev`."""
    if report.get("org") != org or report.get("chain_id") != chain_id:
        return False
    try:
        for entry in report.get("compensations", []):
            if entry.get("status") not in OK_STATUSES:
                continue
            receipt = Receipt.from_dict(entry["receipt"])
            if not (
                verify_receipt(receipt, pub)
                and receipt.status == "committed"
                and receipt.prev == entry["original"]
                and receipt.digest == compensation_digest(org, entry["original"])
                and receipt.intent_id == compensation_intent_id(entry["original"])
            ):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True
