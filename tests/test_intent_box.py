import pytest

from examples.workflow import fixture
from recovery.crypto import generate_keypair
from recovery.intent_box import ContextConflict, IntentBox, verify_update


def test_agents_share_initial_spec_and_cas_updates_are_signed(tmp_path):
    box = IntentBox(tmp_path / "box.db")
    data = fixture("commerce")
    priv, pub = generate_keypair()
    snap = box.create("run", data["initial_guidelines"], data["specification"])
    event = box.append("run", "buyer", "read", "Read specification", priv, expected_version=1)
    assert event["observed_version"] == 1 and event["version"] == 2
    assert verify_update(event, pub)
    assert not verify_update(dict(event, summary="tampered"), pub)
    assert box.append("run", "buyer", "read", "Ignored retry", priv) == event
    with pytest.raises(ContextConflict):
        box.append("run", "merchant", "read", "Stale reader", priv, expected_version=1)
    with pytest.raises(ContextConflict):
        box.revise("run", 2, "changed", data["specification"])
    box.close()
    box = IntentBox(tmp_path / "box.db")
    restored = box.snapshot("run")
    assert restored["spec_hash"] == snap["spec_hash"]
    assert restored["initial_guidelines"] == data["initial_guidelines"]
    assert len(restored["updates"]) == 1
    box.close()


def test_initial_spec_revision_is_explicit_and_freezes_after_start():
    box = IntentBox()
    data = fixture("commerce")
    box.create("run", "Initial instructions", data["specification"])
    revised = box.revise("run", 1, "Corrected instructions", data["specification"])
    assert revised["version"] == 2
    box.set_state("run", "running")
    with pytest.raises(ContextConflict):
        box.revise("run", 2, "bad", data["specification"])
    with pytest.raises(ValueError):
        box.append("run", "outsider", "read", "x", generate_keypair()[0])
    box.close()
