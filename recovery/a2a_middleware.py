"""Glue to the official a2a SDK: metadata helpers, agent-card extension, ASGI wrapper.

The SDK's JSON-RPC dispatcher has a fixed method table, so recovery/resolveIntent is
answered by an ASGI wrapper; every other request is forwarded byte-for-byte.
"""

from __future__ import annotations

import json
from typing import Any

from a2a.types import AgentExtension
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct

from recovery.rpc import METHOD, METHOD_CUT, handle_cut_request, handle_resolve_request
from recovery.service import RecoveryService

X_RECOVERY = "x-recovery"
EXTENSION_URI = "urn:x-recovery:v1"


# ---- metadata (protobuf Struct <-> dict) ----------------------------------------------------


def struct_to_dict(s: Struct | None) -> dict[str, Any]:
    return json_format.MessageToDict(s) if s is not None else {}


def dict_to_struct(d: dict[str, Any]) -> Struct:
    s = Struct()
    json_format.ParseDict(d, s)
    return s


def recovery_block(metadata: Struct | None) -> dict[str, Any]:
    """The x-recovery block of a message's metadata ({} if the peer lacks the extension)."""
    return struct_to_dict(metadata).get(X_RECOVERY, {})


def with_recovery(block: dict[str, Any]) -> Struct:
    return dict_to_struct({X_RECOVERY: block})


# ---- agent card extension (publishes the org's Ed25519 public key) ---------------------------


def recovery_extension(org: str, public_key_hex: str, cut_epoch: int = 0) -> AgentExtension:
    return AgentExtension(
        uri=EXTENSION_URI,
        description="Evidence-based recovery: write-ahead intents, signed receipts, resolveIntent",
        required=False,
        params=dict_to_struct(
            {
                "org": org,
                "public_key": public_key_hex,
                "cut_epoch": cut_epoch,
                "methods": [METHOD, METHOD_CUT],
            }
        ),
    )


def card_public_key(card: Any) -> str | None:
    for ext in card.capabilities.extensions:
        if ext.uri == EXTENSION_URI:
            return struct_to_dict(ext.params).get("public_key")
    return None


# ---- ASGI wrapper ----------------------------------------------------------------------------


class RecoveryASGI:
    """Answer recovery/resolveIntent; pass everything else to the wrapped app unchanged."""

    def __init__(self, app, service: RecoveryService):
        self.app = app
        self.service = service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)

        chunks, more = [], True
        while more:
            msg = await receive()
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        raw = b"".join(chunks)

        body = None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("method") in (METHOD, METHOD_CUT):
                body = parsed
        except ValueError:
            pass

        if body is not None:
            handler = handle_cut_request if body["method"] == METHOD_CUT else handle_resolve_request
            out = json.dumps(handler(self.service, body)).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": out})
            return

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def checkpoint_block(metadata):
    return recovery_block(metadata).get("checkpoint", {})
