import dataclasses

from recovery.crypto import (
    canonical,
    generate_keypair,
    load_private_key,
    public_key_from_hex,
    public_key_hex,
    save_private_key,
    sign,
    verify,
)
from recovery.intents import DigestPolicy, Granularity, Intent, compute_digest, make_intent
from recovery.receipts import Receipt, make_receipt, verify_chain, verify_receipt


def test_canonical_is_order_independent():
    assert canonical({"b": 1, "a": [2, 3]}) == canonical({"a": [2, 3], "b": 1})


def test_sign_verify_and_tamper():
    priv, pub = generate_keypair()
    sig = sign(priv, b"msg")
    assert verify(pub, b"msg", sig)
    assert not verify(pub, b"other", sig)
    assert not verify(pub, b"msg", "zz")  # malformed hex
    _, other = generate_keypair()
    assert not verify(other, b"msg", sig)


def test_key_files_roundtrip(tmp_path):
    priv, pub = generate_keypair()
    p = tmp_path / "k"
    save_private_key(priv, p)
    again = load_private_key(p)
    assert public_key_hex(again.public_key()) == public_key_hex(pub)
    assert verify(public_key_from_hex(public_key_hex(pub)), b"x", sign(again, b"x"))


def test_digest_ignores_irrelevant_fields_and_order():
    a = compute_digest("charge", "acct1", {"amount": 5, "currency": "USD"})
    b = compute_digest("charge", "acct1", {"currency": "USD", "amount": 5})
    assert a == b
    assert a != compute_digest("charge", "acct1", {"amount": 6, "currency": "USD"})


def test_digest_granularity():
    pol = DigestPolicy(medium_keys=("amount",))
    p1 = {"amount": 5, "memo": "a"}
    p2 = {"amount": 5, "memo": "b"}
    p3 = {"amount": 9, "memo": "a"}
    coarse = lambda p: compute_digest("charge", "t", p, pol, Granularity.COARSE)
    medium = lambda p: compute_digest("charge", "t", p, pol, Granularity.MEDIUM)
    fine = lambda p: compute_digest("charge", "t", p, pol, Granularity.FINE)
    assert coarse(p1) == coarse(p2) == coarse(p3)
    assert medium(p1) == medium(p2) != medium(p3)
    assert len({fine(p1), fine(p2), fine(p3)}) == 3


def test_intent_roundtrip():
    i = make_intent("chain", "d" * 64, parent_receipt=None)
    assert Intent.from_dict(i.to_dict()) == i


def _chain(n):
    keys = [generate_keypair() for _ in range(n)]
    chain, prev = [], None
    for idx, (priv, _) in enumerate(keys):
        r = make_receipt(priv, f"i{idx}", f"d{idx}", "committed", f"ref{idx}", prev)
        chain.append(r)
        prev = r.hash
    return chain, [pub for _, pub in keys]


def test_valid_chain_verifies():
    chain, pubs = _chain(3)
    assert verify_chain(chain, pubs) is None
    assert Receipt.from_dict(chain[0].to_dict()) == chain[0]


def test_tampered_field_rejected():
    chain, pubs = _chain(3)
    chain[1] = dataclasses.replace(chain[1], effect_ref="evil")
    assert not verify_receipt(chain[1], pubs[1])
    assert verify_chain(chain, pubs) == 1


def test_wrong_signature_rejected():
    chain, pubs = _chain(2)
    other_priv, _ = generate_keypair()
    forged = make_receipt(other_priv, "i1", "d1", "committed", "ref1", chain[0].hash)
    assert verify_chain([chain[0], forged], pubs) == 1


def test_broken_prev_link_rejected():
    chain, pubs = _chain(3)
    priv, pub = generate_keypair()
    swapped = make_receipt(priv, "iX", "dX", "committed", "r", "0" * 64)
    assert verify_chain([chain[0], swapped], [pubs[0], pub]) == 1
    # head must have prev None
    assert verify_chain([chain[1]], [pubs[1]]) == 0


def test_bad_status_and_dropped_receipt():
    priv, _ = generate_keypair()
    try:
        make_receipt(priv, "i", "d", "weird", None, None)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    chain, pubs = _chain(3)
    assert verify_chain([chain[0], chain[2]], [pubs[0], pubs[2]]) == 1
