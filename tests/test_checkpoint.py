from dataclasses import replace

import pytest

from recovery.checkpoint import (
    Checkpoint,
    compute_cut,
    dominant_cut,
    make_checkpoint,
    verify_checkpoint,
)
from recovery.crypto import generate_keypair
from recovery.intents import make_intent
from recovery.service import RecoveryService
from recovery.store import Store, StoreConflict


def test_signed_roundtrip_and_tampering():
    priv, pub = generate_keypair()
    cp = make_checkpoint(priv, "A", 1, {"A": 2, "B": 1}, "chain")
    assert Checkpoint.from_dict(cp.to_dict()) == cp
    assert verify_checkpoint(pub, cp)
    assert not verify_checkpoint(pub, replace(cp, cut={"A": 3}))
    assert not verify_checkpoint(pub, replace(cp, chain_id="foreign"))
    assert not verify_checkpoint(pub, replace(cp, sig="not-hex"))
    assert not verify_checkpoint(generate_keypair()[1], cp)


@pytest.mark.parametrize(
    "epoch,cut", [(0, {"A": 1}), (1, {"B": 2}), (1, {"A": -1}), (1, {"A": True}), (True, {"A": 1})]
)
def test_invalid_vectors(epoch, cut):
    with pytest.raises(ValueError):
        make_checkpoint(generate_keypair()[0], "A", epoch, cut)


def test_maximum_of_three_observations():
    priv, _ = generate_keypair()
    cuts = [
        make_checkpoint(priv, org, n, vector)
        for n, (org, vector) in enumerate(
            [("A", {"A": 2, "B": 1}), ("B", {"A": 1, "B": 5}), ("C", {"C": 7, "A": 3})], 1
        )
    ]
    assert dominant_cut(cuts) == {"A": 3, "B": 5, "C": 7}
    assert dominant_cut([]) == {}


def test_store_epoch_snapshot_and_reopen(tmp_path):
    path = tmp_path / "a.db"
    priv, pub = generate_keypair()
    store = Store(path, org_id="A")
    service = RecoveryService(store, priv, "A")
    before = store.version
    intent = make_intent("chain", "digest")
    _, receipt = service.execute_effect(intent, lambda: "effect")
    cp = store.export_checkpoint(priv, "A", "chain")
    assert store.snapshot(before) == [receipt]
    assert store.snapshot(store.version) == []
    assert verify_checkpoint(pub, cp)
    assert compute_cut({"A": store}) == {"A": store.version}
    store.close()
    store = Store(path)
    assert store.org_id == "A" and store.checkpoint_epoch == cp.epoch
    assert store.export_checkpoint(priv).epoch == cp.epoch + 1
    with pytest.raises(StoreConflict):
        store.set_org("B")
    store.close()


def test_merge_rejects_cross_org_and_conflicting_receipts():
    priv, _ = generate_keypair()
    a, b = Store(org_id="A"), Store(org_id="B")
    with pytest.raises(StoreConflict):
        a.merge_from(b)
    b = Store(org_id="A")
    intent = make_intent("chain", "digest")
    RecoveryService(a, priv, "A").execute_effect(intent, lambda: "one")
    RecoveryService(b, priv, "A").execute_effect(intent, lambda: "two")
    with pytest.raises(StoreConflict):
        a.merge_from(b)


def test_dominant_cut_three_orgs_and_tampering():
    priv, pub = generate_keypair()
    checkpoints = [
        make_checkpoint(priv, org, 1, cut)
        for org, cut in (("A", {"A": 2, "B": 1}), ("B", {"B": 5}), ("C", {"A": 1, "C": 3}))
    ]
    assert dominant_cut(checkpoints) == {"A": 2, "B": 5, "C": 3}
    assert not verify_checkpoint(pub, replace(checkpoints[0], cut={"A": 9}))
    assert not verify_checkpoint(generate_keypair()[1], checkpoints[0])
    with pytest.raises(ValueError):
        Checkpoint.from_dict({"epoch": -1, "org_id": "A", "cut": {"A": 0}, "sig": ""})


def test_persisted_plans_participate_in_store_versions_and_checkpoint_commitments():
    priv, _ = generate_keypair()
    store = Store(org_id="A")
    before = store.export_checkpoint(priv)
    store.put_plan("chain", "B", {"request": "stable-original"})
    after = store.export_checkpoint(priv)
    assert after.cut["A"] == before.cut["A"] + 1
    assert after.state_digest != before.state_digest
    version = store.version
    assert store.put_plan("chain", "B", {"request": "replanned"}) == {"request": "stable-original"}
    assert store.version == version
    store.close()
