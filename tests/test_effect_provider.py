from concurrent.futures import ThreadPoolExecutor

import pytest

from recovery.crypto import generate_keypair
from recovery.effect_provider import SyntheticEffectProvider
from recovery.intents import make_intent
from recovery.replicas import import_replica_checkpoint
from recovery.service import RecoveryService
from recovery.store import Store, StoreConflict


def test_independent_replicas_race_without_duplicate_effect(tmp_path):
    priv, pub = generate_keypair()
    # Two independently connected providers model one organization's idempotent external tool.
    providers = [SyntheticEffectProvider(tmp_path / "provider.db", priv) for _ in range(2)]
    services = [
        RecoveryService(Store(tmp_path / f"r{i}.db"), priv, "A", provider=p)
        for i, p in enumerate(providers)
    ]
    intents = [make_intent("chain", "same-action") for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda args: args[0].execute_provider(args[1], "logical-slot"),
                zip(services, intents, strict=True),
            )
        )
    assert outcomes[0][1].hash == outcomes[1][1].hash
    assert providers[0].counts("chain")["effects"] == 1
    with pytest.raises(StoreConflict):
        providers[1].apply(make_intent("chain", "changed-action"), "logical-slot")
    cp = services[0].store.export_checkpoint(priv, chain_id="chain", include_receipts=True)
    assert import_replica_checkpoint(services[1], cp, pub) == 0
    for s in services:
        s.store.close()
    for p in providers:
        p.close()


def test_tombstone_survives_restart_and_blocks_late_delivery(tmp_path):
    priv, _ = generate_keypair()
    path = tmp_path / "p.db"
    provider = SyntheticEffectProvider(path, priv)
    intent = make_intent("chain", "d")
    assert provider.resolve("chain", intent.intent_id, "d").status == "tombstone"
    provider.close()
    provider = SyntheticEffectProvider(path, priv)
    with pytest.raises(StoreConflict):
        provider.apply(intent, "slot")
    with pytest.raises(StoreConflict):
        provider.apply(make_intent("foreign", "d", intent_id=intent.intent_id), "slot")
    fresh = make_intent("chain", "d")
    assert provider.apply(fresh, "slot").status == "committed"
    provider.close()


def test_effect_without_local_receipt_is_recovered_by_another_replica(tmp_path):
    priv, _ = generate_keypair()
    provider = SyntheticEffectProvider(tmp_path / "p.db", priv)
    intent = make_intent("chain", "d")
    provider.apply(intent, "slot")  # caller crashes before writing its local receipt
    service = RecoveryService(Store(tmp_path / "replica.db"), priv, "A", provider=provider)
    result = service.resolve("chain", intent.intent_id, "d")
    assert result["state"] == "committed"
    assert service.resolve("foreign", intent.intent_id, "d")["state"] == "quarantine"
    assert service.store.get_receipt(intent.intent_id).effect_ref == result["receipt"]["effect_ref"]
    assert provider.counts("chain")["effects"] == 1
    service.store.close()
    provider.close()
