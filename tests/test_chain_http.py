import asyncio
import uuid

import httpx
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest

from agents.app import build_app, build_card, free_port, serve
from agents.chain_agent import ChainAgentExecutor
from agents.tools.counter import EffectCounter
from recovery.a2a_middleware import card_public_key, recovery_block, with_recovery
from recovery.crypto import generate_keypair, public_key_from_hex, public_key_hex
from recovery.intents import compute_digest, make_intent
from recovery.receipts import Receipt, verify_chain
from recovery.rpc import resolve_remote
from recovery.service import RecoveryService
from recovery.store import Store


class Hop:
    def __init__(self, name, downstream=None, extension=True):
        self.name = name
        self.priv, _ = generate_keypair()
        self.service = RecoveryService(Store(), self.priv, name)
        self.tool = EffectCounter(name)
        port = free_port()
        self.url = f"http://127.0.0.1:{port}"
        card = build_card(name, self.url, self.service, extension)
        ex = ChainAgentExecutor(name, self.service, self.tool, downstream)
        self.running = serve(build_app(ex, card, self.service, extension), port)

    def stop(self):
        self.running.stop()


@pytest.fixture
def chain():
    c = Hop("C")
    b = Hop("B", c.url)
    a = Hop("A", b.url)
    yield a, b, c
    for h in (a, b, c):
        h.stop()


async def send(url, text, intent=None):
    msg = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=text)])
    if intent is not None:
        msg.metadata.CopyFrom(with_recovery({"intent": intent.to_dict()}))
    async with httpx.AsyncClient(timeout=20) as http:
        client = await ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create_from_url(url)
        async for resp in client.send_message(SendMessageRequest(message=msg)):
            if resp.HasField("message"):
                return resp.message
    raise AssertionError("no message in response")


def test_happy_path_chain_with_receipts(chain):
    a, b, c = chain
    intent = make_intent("chain-1", compute_digest("do_work", "start", {"task": "t1"}))
    msg = asyncio.run(send(a.url, "t1", intent))
    block = recovery_block(msg.metadata)
    assert (a.tool.count, b.tool.count, c.tool.count) == (1, 1, 1)

    ra = Receipt.from_dict(block["receipt"])
    rb = Receipt.from_dict(block["downstream"]["receipt"])
    rc = Receipt.from_dict(block["downstream"]["downstream"]["receipt"])
    pubs = [public_key_from_hex(public_key_hex(h.priv.public_key())) for h in (a, b, c)]
    assert verify_chain([ra, rb, rc], pubs) is None


def test_agent_card_publishes_key(chain):
    a, _, _ = chain

    async def fetch():
        async with httpx.AsyncClient() as http:
            r = await http.get(a.url + "/.well-known/agent-card.json")
            return r.json()

    card = asyncio.run(fetch())
    exts = card["capabilities"]["extensions"]
    assert exts[0]["uri"] == "urn:x-recovery:v1"
    assert exts[0]["params"]["public_key"] == public_key_hex(a.priv.public_key())
    from a2a.types import AgentCard
    from google.protobuf import json_format

    parsed = json_format.ParseDict(card, AgentCard())
    assert card_public_key(parsed) == public_key_hex(a.priv.public_key())


def test_plain_a2a_client_without_extension_still_works(chain):
    a, b, c = chain
    msg = asyncio.run(send(a.url, "plain"))  # no x-recovery metadata at all
    assert "A done" in msg.parts[0].text
    assert (a.tool.count, b.tool.count, c.tool.count) == (1, 1, 1)


def test_resolve_intent_rpc_and_replan_dedup(chain):
    a, _, _ = chain
    d = compute_digest("do_work", "start", {"task": "t2"})
    i1 = make_intent("chain-2", d)
    asyncio.run(send(a.url, "t2", i1))
    assert a.tool.count == 1

    # committed intent resolves as committed
    res = asyncio.run(resolve_remote(a.url, "chain-2", i1.intent_id, d))
    assert res["state"] == "committed"

    # re-planned request: new intent id, same digest -> dedup, no second effect
    i2 = make_intent("chain-2", d)
    msg = asyncio.run(send(a.url, "t2", i2))
    assert a.tool.count == 1
    assert recovery_block(msg.metadata)["status"] == "done"
    res2 = asyncio.run(resolve_remote(a.url, "chain-2", i2.intent_id, d))
    assert res2["state"] == "committed"

    # never-seen intent gets a durable tombstone
    res3 = asyncio.run(resolve_remote(a.url, "chain-2", "ghost", "other-digest"))
    assert res3["state"] == "tombstone"
    again = asyncio.run(resolve_remote(a.url, "chain-2", "ghost", "other-digest"))
    assert again["state"] == "tombstone"
