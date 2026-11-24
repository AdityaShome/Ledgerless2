from dataclasses import replace

import httpx
import pytest

from recovery.a2a_middleware import RecoveryASGI, checkpoint_block, with_recovery
from recovery.checkpoint import make_checkpoint
from recovery.crypto import generate_keypair
from recovery.cut_protocol import CutRequest, CutResponse, gather_cut, reconcile_cut
from recovery.rpc import query_cut_remote
from recovery.service import RecoveryService
from recovery.store import Store


async def fallback(scope, receive, send):
    await send({"type": "http.response.start", "status": 404, "headers": []})
    await send({"type": "http.response.body", "body": b"missing"})


def peers():
    keys = {org: generate_keypair() for org in "ABC"}
    cps = {org: make_checkpoint(priv, org, 1, {org: 2}, "chain") for org, (priv, _) in keys.items()}
    return keys, cps, {org: pub for org, (_, pub) in keys.items()}


def test_reconcile_valid_missing_conflicts_and_rollback():
    keys, cps, pubs = peers()
    local = Store(org_id="observer")
    result = reconcile_cut(local, cps, pubs)
    assert result.dominant_cut == {"A": 2, "B": 2, "C": 2}
    assert not result.missing_at and not result.conflicts
    assert not result.causally_verified  # vector max is not a causal snapshot
    assert reconcile_cut(local, {"A": cps["A"]}, pubs).missing_at == ["B", "C"]
    bad = dict(cps, A=replace(cps["A"], sig="00"))
    assert reconcile_cut(local, bad, pubs).conflicts
    newer = make_checkpoint(keys["A"][0], "A", 3, {"A": 4}, "chain")
    assert not reconcile_cut(local, dict(cps, A=newer), pubs).conflicts
    assert reconcile_cut(local, cps, pubs).conflicts  # stale epoch
    fork = make_checkpoint(keys["A"][0], "A", 3, {"A": 5}, "chain")
    assert reconcile_cut(local, dict(cps, A=fork), pubs).conflicts
    regressed = make_checkpoint(keys["A"][0], "A", 4, {"A": 1}, "chain")
    assert reconcile_cut(local, dict(cps, A=regressed), pubs).conflicts


def test_dependency_gap_and_scope_mismatch():
    keys, cps, pubs = peers()
    cps["A"] = make_checkpoint(keys["A"][0], "A", 1, {"A": 2, "B": 8}, "chain")
    assert reconcile_cut(Store(), cps, pubs).missing_at == ["B"]
    cps["C"] = make_checkpoint(keys["C"][0], "C", 1, {"C": 2}, "other")
    assert reconcile_cut(Store(), cps, pubs).conflicts


async def test_gather_three_rpc_endpoints_and_persist_epochs():
    services = {org: RecoveryService(Store(), generate_keypair()[0], org) for org in "ABC"}
    apps = {org.lower(): RecoveryASGI(fallback, service) for org, service in services.items()}

    async def route(request):
        transport = httpx.ASGITransport(app=apps[request.url.host])
        async with httpx.AsyncClient(transport=transport, base_url=str(request.url)) as client:
            return await client.post("/", content=request.content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http:
        cps = await gather_cut(["http://a", "http://b", "http://c"], "chain", http)
        assert set(cps) == set("ABC")
        cp2 = await query_cut_remote("http://a", "chain", http)
        assert cp2.epoch == cps["A"].epoch + 1
    assert CutResponse.from_dict(CutResponse(cp2).to_dict()).checkpoint == cp2
    assert CutRequest("chain").to_dict() == {"chain_id": "chain"}
    assert checkpoint_block(with_recovery({"checkpoint": cp2.to_dict()}))["org_id"] == "A"


async def test_bad_rpc_params_and_unavailable_peer():
    app = RecoveryASGI(fallback, RecoveryService(Store(), generate_keypair()[0], "A"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://a"
    ) as http:
        response = await http.post("/", json={"id": 1, "method": "recovery/queryCut"})
        assert response.json()["error"]["code"] == -32602

    async def fail(request):
        raise httpx.ConnectError("offline")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        with pytest.raises(RuntimeError):
            await gather_cut(["http://offline"], "chain", http)


def test_receipt_cut_requires_parent_evidence_and_verifies_manifests():
    from recovery.intents import make_intent

    keys, _, pubs = peers()
    services = {org: RecoveryService(Store(), keys[org][0], org) for org in "ABC"}
    prev = None
    cps = {}
    for org, service in services.items():
        intent = make_intent("chain", "work", parent_receipt=prev)
        _, receipt = service.execute_effect(intent, lambda: "effect")
        prev = receipt.hash
        cps[org] = service.store.export_checkpoint(
            service.priv, chain_id="chain", include_receipts=True
        )
    observer = Store(org_id="observer")
    result = reconcile_cut(observer, cps, pubs)
    assert result.causally_verified
    assert not result.missing_at and not result.conflicts
    only_child = reconcile_cut(Store(), {"C": cps["C"]}, {"C": pubs["C"]})
    assert any(item.startswith("receipt:") for item in only_child.missing_at)
    assert not only_child.causally_verified
    malformed = make_checkpoint(
        keys["C"][0],
        "C",
        2,
        {"C": 2},
        "chain",
        receipts=[dict(cps["C"].receipts[0], effect_ref="tampered")],
    )
    assert reconcile_cut(Store(), {"C": malformed}, {"C": pubs["C"]}).conflicts


def test_same_version_different_store_contents_conflict():
    priv, pub = generate_keypair()
    a = make_checkpoint(priv, "A", 1, {"A": 2}, "chain", state_digest="first")
    fork = make_checkpoint(priv, "A", 2, {"A": 2}, "chain", state_digest="second")
    store = Store()
    assert not reconcile_cut(store, {"A": a}, {"A": pub}).conflicts
    assert reconcile_cut(store, {"A": fork}, {"A": pub}).conflicts


async def test_query_cut_includes_signed_receipt_evidence():
    from recovery.intents import make_intent

    priv, pub = generate_keypair()
    service = RecoveryService(Store(), priv, "A")
    service.execute_effect(make_intent("chain", "work"), lambda: "effect")
    app = RecoveryASGI(fallback, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://a"
    ) as http:
        cp = await query_cut_remote("http://a", "chain", http)
    assert len(cp.receipts) == 1
    result = reconcile_cut(Store(), {"A": cp}, {"A": pub})
    assert result.causally_verified and not result.conflicts
