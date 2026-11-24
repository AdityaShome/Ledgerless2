import pytest

from recovery.crypto import generate_keypair
from recovery.decide import Action, Evidence, decide
from recovery.intents import make_intent
from recovery.receipts import make_receipt
from recovery.store import Store, StoreConflict

PRIV, _ = generate_keypair()


def rcpt(intent_id="i1", digest="d1", status="committed"):
    return make_receipt(PRIV, intent_id, digest, status, "ref", None)


# ---- decide: one test per row of guide 3.4 --------------------------------


def test_row1_valid_receipt_resume():
    assert decide(Evidence(receipt=rcpt(), intent_declared=True)) is Action.RESUME


def test_row2_tombstone_replay():
    assert decide(Evidence(receipt=rcpt(status="tombstone"), intent_declared=True)) is Action.REPLAY


def test_row3_in_doubt_reachable_resolve():
    assert decide(Evidence(intent_declared=True, callee_reachable=True)) is Action.RESOLVE


def test_row4_unreachable_past_timeout_quarantine():
    e = Evidence(intent_declared=True, callee_reachable=False, timed_out=True)
    assert decide(e) is Action.QUARANTINE


def test_row5_receipt_upstream_aborted_compensate():
    e = Evidence(receipt=rcpt(), intent_declared=True, upstream_aborted=True)
    assert decide(e) is Action.COMPENSATE


def test_row6_bad_signature_quarantine_alert():
    e = Evidence(receipt=rcpt(), signature_valid=False, intent_declared=True)
    assert decide(e) is Action.QUARANTINE_ALERT


# ---- decide: cases the table leaves open (logged in DECISIONS.md) ----------


def test_bad_signature_beats_upstream_abort():
    e = Evidence(receipt=rcpt(), signature_valid=False, upstream_aborted=True)
    assert decide(e) is Action.QUARANTINE_ALERT


def test_unreachable_before_timeout_waits():
    e = Evidence(intent_declared=True, callee_reachable=False, timed_out=False)
    assert decide(e) is Action.WAIT


def test_resolve_unknown_waits_then_quarantines():
    assert decide(Evidence(intent_declared=True, resolve_unknown=True)) is Action.WAIT
    e = Evidence(intent_declared=True, resolve_unknown=True, timed_out=True)
    assert decide(e) is Action.QUARANTINE


def test_no_intent_no_receipt_replays_or_discards():
    assert decide(Evidence()) is Action.REPLAY
    assert decide(Evidence(upstream_aborted=True)) is Action.DISCARD


def test_tombstone_with_upstream_abort_discards():
    e = Evidence(receipt=rcpt(status="tombstone"), upstream_aborted=True)
    assert decide(e) is Action.DISCARD


# ---- store -----------------------------------------------------------------


def test_intent_and_state_progression():
    s = Store()
    i = make_intent("c", "d1", intent_id="i1")
    assert s.state("i1") is None
    s.record_intent(i)
    s.record_intent(i)  # idempotent
    assert s.state("i1") == "declared" and s.get_intent("i1") == i
    s.put_receipt("c", rcpt())
    assert s.state("i1") == "committed"


def test_version_is_monotonic():
    s = Store()
    v0 = s.version
    s.record_intent(make_intent("c", "d1", intent_id="i1"))
    s.put_receipt("c", rcpt())
    assert s.version == v0 + 2


def test_committed_never_overwritten_and_not_tombstonable():
    s = Store()
    s.put_receipt("c", rcpt())
    s.put_receipt("c", rcpt())  # identical: idempotent
    with pytest.raises(StoreConflict):
        s.put_receipt("c", rcpt(status="tombstone"))


def test_tombstoned_cannot_commit():
    s = Store()
    s.put_receipt("c", rcpt(status="tombstone"))
    with pytest.raises(StoreConflict):
        s.put_receipt("c", rcpt())


def test_digest_dedup_across_intent_ids():
    s = Store()
    s.put_receipt("c", rcpt("i1", "dd"))
    assert s.committed_for_digest("c", "dd").intent_id == "i1"
    assert s.committed_for_digest("other-chain", "dd") is None
    with pytest.raises(StoreConflict):  # re-planned request, same digest
        s.put_receipt("c", rcpt("i2", "dd"))


def test_replay_after_tombstone_with_new_intent_allowed():
    s = Store()
    s.put_receipt("c", rcpt("i1", "dd", "tombstone"))
    s.put_receipt("c", rcpt("i2", "dd"))
    assert s.state("i1") == "tombstone" and s.state("i2") == "committed"


def test_merge_is_union_and_persists(tmp_path):
    a, b = Store(), Store(tmp_path / "b.db")
    a.put_receipt("c", rcpt("i1", "d1"))
    b.put_receipt("c", rcpt("i2", "d2"))
    b.record_intent(make_intent("c", "d3", intent_id="i3"))
    assert a.merge_from(b) == 1
    assert a.state("i1") == "committed" and a.state("i2") == "committed"
    assert a.state("i3") == "declared"
    assert a.merge_from(b) == 0
    b.close()
    again = Store(tmp_path / "b.db")  # durable across reopen
    assert again.state("i2") == "committed"
