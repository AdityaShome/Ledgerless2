"""One A2A send/recover path used by demo roots and downstream delegations."""

from __future__ import annotations

import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest

from recovery.a2a_middleware import recovery_block, with_recovery
from recovery.decide import Action, Evidence, decide
from recovery.intents import make_intent
from recovery.receipts import Receipt, verify_receipt
from recovery.rpc import resolve_remote


async def send_message(
    url, text, intent, http, *, pub=None, retries=2, metadata=None, retry_url=None
):
    current = intent
    decisions = []
    for attempt in range(retries + 1):
        endpoint = retry_url if attempt and retry_url else url
        block = dict(metadata or {})
        if current:
            block["intent"] = current.to_dict()
        if attempt:
            block["replay"] = True
        message = Message(
            message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=text)]
        )
        if block:
            message.metadata.CopyFrom(with_recovery(block))
        try:
            client = await ClientFactory(
                ClientConfig(httpx_client=http, streaming=False)
            ).create_from_url(endpoint)
            async for response in client.send_message(SendMessageRequest(message=message)):
                if response.HasField("message"):
                    result = recovery_block(response.message.metadata)
                    if current and pub is not None and result.get("receipt"):
                        receipt = Receipt.from_dict(result["receipt"])
                        if receipt.digest != current.digest or not verify_receipt(receipt, pub):
                            return {
                                "status": "quarantine",
                                "alert": True,
                                "reason": "invalid receipt signature or digest",
                            }
                    if decisions:
                        result["recovery_decisions"] = decisions
                    return result
            raise RuntimeError("A2A peer returned no message")
        except (httpx.HTTPError, RuntimeError) as exc:
            error = type(exc).__name__
        except Exception as exc:
            # SDK wraps transport/RPC errors in version-specific exception classes.
            if not type(exc).__module__.startswith("a2a."):
                raise
            error = type(exc).__name__
        if current is None or pub is None:
            return {"status": "quarantine", "reason": f"unresolved A2A response: {error}"}
        if attempt == retries:
            return {
                "status": "quarantine",
                "reason": "recovery retry budget exhausted",
                "recovery_decisions": decisions,
            }
        for resolve_attempt in range(2):
            try:
                resolved = await resolve_remote(
                    retry_url or endpoint,
                    current.chain_id,
                    current.intent_id,
                    current.digest,
                    http=http,
                )
                if resolved["state"] == "quarantine":
                    return {
                        "status": "quarantine",
                        "reason": resolved.get("reason", "binding conflict"),
                    }
                receipt = (
                    Receipt.from_dict(resolved["receipt"]) if resolved.get("receipt") else None
                )
                evidence = Evidence(
                    receipt=receipt,
                    signature_valid=bool(
                        receipt
                        and verify_receipt(receipt, pub)
                        and receipt.digest == current.digest
                    ),
                    intent_declared=True,
                    resolve_unknown=resolved["state"] == "unknown",
                    timed_out=True,
                )
                break
            except (httpx.HTTPError, RuntimeError):
                evidence = Evidence(intent_declared=True, callee_reachable=False, timed_out=True)
                if resolve_attempt == 0:
                    continue
        action = decide(evidence)
        decisions.append(action.value)
        if action is Action.REPLAY:
            current = make_intent(current.chain_id, current.digest, current.parent_receipt)
        elif action is not Action.RESUME:
            return {
                "status": "quarantine",
                "alert": action is Action.QUARANTINE_ALERT,
                "reason": action.value,
                "recovery_decisions": decisions,
            }
    raise AssertionError("unreachable")
