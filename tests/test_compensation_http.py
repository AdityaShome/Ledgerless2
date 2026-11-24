"""Upstream abort over real A2A HTTP: every hop compensates from its own signed receipts."""

import asyncio
import dataclasses
import json

import httpx
import pytest

from agents.app import build_app, build_card, free_port, serve
from agents.chain_agent import ChainAgentExecutor
from agents.tools.counter import EffectCounter
from recovery.a2a_middleware import recovery_block
from recovery.compensation import compensation_digest, compensation_intent_id
from recovery.crypto import generate_keypair
from recovery.cut_protocol import gather_cut, reconcile_cut
from recovery.intents import compute_digest, make_intent
from recovery.receipts import Receipt, verify_receipt
from recovery.rpc import compensate_remote
from recovery.service import RecoveryService
from recovery.store import Store
from tests.test_chain_http import send

ORDER: list[str] = []  # global order in which external compensations ran


class RecordingTool(EffectCounter):
    def compensate(self, effect_ref):
        ORDER.append(self.name)
        return super().compensate(effect_ref)


class NoUndoTool:
    """A tool whose effects cannot be compensated."""

    def __init__(self, name):
        self.name, self.count = name, 0

    def apply(self, detail=""):
        self.count += 1
        return f"{self.name}-{self.count}"


class Hop:
    def __init__(self, name, downstream=None, tool=None):
        self.name = name
        self.priv, self.pub = generate_keypair()
        self.service = RecoveryService(Store(), self.priv, name)
        self.tool = tool or RecordingTool(name)
        port = free_port()
        self.url = f"http://127.0.0.1:{port}"
        card = build_card(name, self.url, self.service, True)
        ex = ChainAgentExecutor(name, self.service, self.tool, downstream)
        self.running = serve(build_app(ex, card, self.service, True), port)

    def stop(self):
        self.running.stop()


@pytest.fixture
def chain():
    ORDER.clear()
    c = Hop("C")
    b = Hop("B", c.url)
    a = Hop("A", b.url)
    yield a, b, c
    for h in (a, b, c):
        h.stop()


def run_chain(a, chain_id, task):
    intent = make_intent(chain_id, compute_digest("do_work", "start", {"task": task}))
    msg = asyncio.run(send(a.url, task, intent))
    block = recovery_block(msg.metadata)
    forward = {
        "A": Receipt.from_dict(block["receipt"]),
        "B": Receipt.from_dict(block["downstream"]["receipt"]),
        "C": Receipt.from_dict(block["downstream"]["downstream"]["receipt"]),
    }
    return forward


def abort(url, chain_id):
    async def go():
        async with httpx.AsyncClient(timeout=30) as http:
            return await compensate_remote(url, chain_id, http)

    return asyncio.run(go())


def test_abort_compensates_whole_chain_in_reverse_from_receipts(chain):
    a, b, c = chain
    forward = run_chain(a, "abort-1", "t")
    assert (a.tool.net, b.tool.net, c.tool.net) == (1, 1, 1)

    report = abort(a.url, "abort-1")

    assert report["status"] == "compensated"
    assert (a.tool.net, b.tool.net, c.tool.net) == (0, 0, 0)
    assert ORDER == ["C", "B", "A"]  # saga order: downstream first

    # Each compensation receipt is signed by its own hop, linked to the receipt that hop
    # produced on the forward path, and bound to exactly that effect.
    levels = {
        "A": (report, a),
        "B": (report["downstream"], b),
        "C": (report["downstream"]["downstream"], c),
    }
    for org, (level, hop) in levels.items():
        assert level["org"] == org
        (entry,) = level["compensations"]
        assert entry["action"] == "compensate" and entry["status"] == "compensated"
        assert entry["original"] == forward[org].hash
        receipt = Receipt.from_dict(entry["receipt"])
        assert verify_receipt(receipt, hop.pub)
        assert receipt.prev == forward[org].hash
        assert receipt.digest == compensation_digest(org, forward[org].hash)
        assert receipt.intent_id == compensation_intent_id(forward[org].hash)


def test_compensation_receipts_reconcile_in_the_cut(chain):
    a, b, c = chain
    run_chain(a, "abort-cut", "t")
    abort(a.url, "abort-cut")

    async def cut():
        async with httpx.AsyncClient() as http:
            return await gather_cut([a.url, b.url, c.url], "abort-cut", http)

    checkpoints = asyncio.run(cut())
    observer = Store(org_id="observer")
    try:
        result = reconcile_cut(observer, checkpoints, {h.name: h.pub for h in (a, b, c)})
    finally:
        observer.close()
    assert not result.conflicts and not result.missing_at
    assert result.causally_verified
    assert all(len(cp.receipts) == 2 for cp in checkpoints.values())  # effect + compensation


def test_abort_is_idempotent(chain):
    a, b, c = chain
    run_chain(a, "abort-2", "t")
    first = abort(a.url, "abort-2")
    again = abort(a.url, "abort-2")

    assert again["status"] == "compensated"
    assert (a.tool.compensated, b.tool.compensated, c.tool.compensated) == (1, 1, 1)
    entry = again["compensations"][0]
    assert entry["status"] == "already_compensated"
    assert entry["receipt"] == first["compensations"][0]["receipt"]


def test_abort_with_no_evidence_compensates_nothing(chain):
    a, b, c = chain
    report = abort(a.url, "never-ran")
    assert report["status"] == "compensated"
    assert report["compensations"] == []
    assert (a.tool.compensated, b.tool.compensated, c.tool.compensated) == (0, 0, 0)


def test_unreachable_downstream_does_not_block_upstream_compensation(chain):
    a, b, c = chain
    run_chain(a, "abort-3", "t")
    c.stop()

    report = abort(a.url, "abort-3")

    assert report["status"] == "quarantine"  # C's effect is unresolved, so say so
    assert report["downstream"]["status"] == "quarantine"
    assert report["downstream"]["downstream"]["status"] == "quarantine"
    assert (a.tool.net, b.tool.net, c.tool.net) == (0, 0, 1)  # A and B proved theirs


def test_tampered_receipt_is_quarantined_with_alert_and_not_compensated(chain):
    a, b, c = chain
    run_chain(a, "abort-4", "t")
    store = b.service.store
    ((intent_id, body),) = store.db.execute(
        "SELECT intent_id, body FROM receipts WHERE chain_id='abort-4'"
    ).fetchall()
    forged = dataclasses.replace(Receipt.from_dict(json.loads(body)), effect_ref="forged-ref")
    store.db.execute(
        "UPDATE receipts SET body=? WHERE intent_id=?", (json.dumps(forged.to_dict()), intent_id)
    )
    store.db.commit()

    report = abort(a.url, "abort-4")

    assert report["status"] == "quarantine"
    (entry,) = report["downstream"]["compensations"]
    assert entry["action"] == "quarantine_alert" and entry["alert"] is True
    assert (a.tool.net, b.tool.net, c.tool.net) == (0, 1, 0)  # B untouched; the rest undone


def test_tool_without_compensation_is_quarantined_and_blocks_nothing_else():
    ORDER.clear()
    c = Hop("C")
    b = Hop("B", c.url, tool=NoUndoTool("B"))
    a = Hop("A", b.url)
    try:
        run_chain(a, "abort-5", "t")
        report = abort(a.url, "abort-5")
        (entry,) = report["downstream"]["compensations"]
        assert entry["status"] == "quarantine" and "unsupported" in entry["reason"]
        assert report["status"] == "quarantine"
        assert (a.tool.net, c.tool.net) == (0, 0)
        # nothing was declared for the unsupported effect, so a later retry is not blocked
        assert b.service.store.unresolved_intents("abort-5") == []
    finally:
        for h in (a, b, c):
            h.stop()


def test_compensate_not_served_without_a_compensator():
    from recovery.a2a_middleware import RecoveryASGI

    seen = []

    async def fallback(scope, receive, send):
        seen.append(json.loads((await receive())["body"])["method"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    app = RecoveryASGI(fallback, RecoveryService(Store(), generate_keypair()[0], "A"))
    body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "recovery/compensate"}).encode()

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as h:
            await h.post("/", content=body)

    asyncio.run(call())
    assert seen == ["recovery/compensate"]  # passed through to the wrapped app
