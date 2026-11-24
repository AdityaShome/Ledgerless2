"""Reconcile signed same-organization receipt evidence, never another private DB."""

from recovery.checkpoint import verify_checkpoint
from recovery.receipts import Receipt, verify_receipt
from recovery.store import StoreConflict


def import_replica_checkpoint(service, checkpoint, public_key):
    if checkpoint.org_id != service.org or not verify_checkpoint(public_key, checkpoint):
        raise StoreConflict("untrusted replica checkpoint")
    receipts = [Receipt.from_dict(body) for body in checkpoint.receipts]
    if not all(verify_receipt(r, public_key) for r in receipts):
        raise StoreConflict("invalid replica receipt")
    added = 0
    with service.store.lock:
        # Preflight all conflicts so an invalid manifest cannot partially mutate the store.
        for receipt in receipts:
            if not service.store.binding_matches(
                checkpoint.chain_id, receipt.intent_id, receipt.digest
            ):
                raise StoreConflict("replica task-binding mismatch")
            existing = service.store.get_receipt(receipt.intent_id)
            if existing is not None and existing != receipt:
                raise StoreConflict("replica history conflict")
            dup = service.store.committed_for_digest(checkpoint.chain_id, receipt.digest)
            if receipt.status == "committed" and dup and dup != receipt:
                raise StoreConflict("replica digest conflict")
        for receipt in receipts:
            if service.store.get_receipt(receipt.intent_id) is None:
                service.store.put_receipt(checkpoint.chain_id, receipt)
                added += 1
    return added
