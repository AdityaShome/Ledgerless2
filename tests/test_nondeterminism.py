import pytest

from recovery.crypto import generate_keypair
from recovery.decide import Action, Evidence, decide
from recovery.receipts import make_receipt


@pytest.mark.parametrize("guard,expected", [(None, None), ("x", None), ("x", "y")])
def test_nondeterminism_requires_verified_match(guard, expected):
    assert (
        decide(
            Evidence(
                nondeterministic_replay=True,
                replay_guard_hash=guard,
                expected_replay_guard_hash=expected,
            )
        )
        is Action.QUARANTINE
    )


def test_matching_guard_allows_safe_replay_not_false_resume():
    # A trace match is not a signed proof that the effect committed.
    assert (
        decide(
            Evidence(
                nondeterministic_replay=True,
                replay_guard_hash="same",
                expected_replay_guard_hash="same",
            )
        )
        is Action.REPLAY_SAFE
    )
    assert decide(Evidence()) is Action.REPLAY
    assert Action.REPLAY_SAFE is Action.REPLAY


def test_committed_receipt_resumes_but_tombstone_replay_is_guarded():
    priv, _ = generate_keypair()
    receipt = make_receipt(priv, "i", "d", "committed", "effect", None)
    assert decide(Evidence(receipt=receipt, nondeterministic_replay=True)) is Action.RESUME
    tomb = make_receipt(priv, "i", "d", "tombstone", None, None)
    assert decide(Evidence(receipt=tomb, nondeterministic_replay=True)) is Action.QUARANTINE
    assert (
        decide(Evidence(receipt=tomb, upstream_aborted=True, nondeterministic_replay=True))
        is Action.DISCARD
    )
    assert (
        decide(Evidence(receipt=receipt, signature_valid=False, nondeterministic_replay=True))
        is Action.QUARANTINE_ALERT
    )
