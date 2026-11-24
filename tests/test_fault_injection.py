import asyncio

from bench.hop import Hop
from bench.runner import run
from recovery.crypto import generate_keypair
from recovery.intents import make_intent
from recovery.service import RecoveryService
from recovery.store import Store, StoreConflict


async def test_fault_suite_exposes_baseline_failures():
    results = await run(repeats=2)
    assert len(results) == 40
    assert all(r.passed for r in results if r.baseline == "ledgerless")
    assert any(r.duplicate_executions for r in results if r.baseline == "default_sdk")
    assert any(r.wrong_task_recoveries for r in results if r.baseline == "default_sdk")
    assert any(r.quarantine_rate for r in results if r.baseline == "mesh_quarantine_sim")


async def test_concurrent_replanned_requests_dedup_before_effect():
    hop = Hop("A")
    intents = [make_intent("chain", "same-action") for _ in range(20)]
    await asyncio.gather(*(hop.execute(intent) for intent in intents))
    assert hop.effects == 1


def test_foreign_chain_rejected_and_crash_window_unresolved(tmp_path):
    priv, _ = generate_keypair()
    store = Store(tmp_path / "a.db")
    service = RecoveryService(store, priv, "A")
    intent = make_intent("chain", "d", intent_id="task")
    service.begin(intent)
    store.close()  # crash before receipt: external effect outcome cannot be inferred
    store = Store(tmp_path / "a.db")
    service = RecoveryService(store, priv, "A")
    assert service.resolve("chain", "task", "d")["state"] == "unknown"
    assert service.begin(intent)[0] == "pending"
    assert service.begin(make_intent("chain", "d"))[0] == "pending"
    assert service.resolve("chain", "fresh-id", "d")["state"] == "unknown"
    assert service.resolve("foreign", "task", "d")["state"] == "quarantine"
    try:
        service.begin(make_intent("foreign", "d", intent_id="task"))
    except StoreConflict:
        pass
    else:
        raise AssertionError("foreign chain accepted")


def test_replanned_id_cannot_bypass_uncertain_effect_after_restart(tmp_path):
    priv, _ = generate_keypair()
    path = tmp_path / "uncertain.db"
    store = Store(path)
    service = RecoveryService(store, priv, "A")
    first = make_intent("chain", "effect")
    assert service.begin(first)[0] == "proceed"
    store.close()
    service = RecoveryService(Store(path), priv, "A")
    second = make_intent("chain", "effect")
    assert service.begin(second)[0] == "pending"
    assert service.resolve(second.chain_id, second.intent_id, second.digest)["state"] == "unknown"
