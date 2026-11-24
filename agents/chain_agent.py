"""A chain hop: performs one effect, then delegates to the next hop (A -> B -> C).

With the recovery extension: write-ahead intent, digest dedup, signed receipt returned in
message metadata. Without it (plain A2A client): just does the work.
"""

from __future__ import annotations

import uuid

import httpx
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.types import Message, Part, Role

from agents.tools.counter import EffectCounter
from recovery.a2a_middleware import recovery_block, with_recovery
from recovery.checkpoint import Checkpoint
from recovery.cut_protocol import reconcile_cut
from recovery.decide import Action, Evidence, decide
from recovery.intents import Intent, compute_digest, make_intent
from recovery.service import RecoveryService
from recovery.store import StoreConflict


def reply(text: str, block: dict | None = None, ctx: RequestContext | None = None) -> Message:
    msg = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_AGENT, parts=[Part(text=text)])
    if block:
        msg.metadata.CopyFrom(with_recovery(block))
    if ctx is not None:
        if ctx.context_id:
            msg.context_id = ctx.context_id
        if ctx.task_id:
            msg.task_id = ctx.task_id
    return msg


class ChainAgentExecutor(AgentExecutor):
    def __init__(
        self,
        name: str,
        service: RecoveryService,
        tool: EffectCounter,
        downstream_url: str | None = None,
        action_type: str = "do_work",
        nondeterministic: bool = False,
        peer_keys: dict | None = None,
        downstream_digest=None,
        downstream_retry_url: str | None = None,
        after_commit=None,
        before_execute=None,
        on_result=None,
    ):
        self.downstream_digest = downstream_digest
        self.downstream_retry_url = downstream_retry_url
        self.after_commit = after_commit
        self.before_execute = before_execute
        self.on_result = on_result
        self.nondeterministic = nondeterministic
        self.discover_demo_keys = peer_keys is None
        self.peer_keys = dict(peer_keys or {})
        self.name = name
        self.service = service
        self.tool = tool
        self.downstream_url = downstream_url
        self.action_type = action_type

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        block = recovery_block(context.message.metadata if context.message else None)
        out: dict = {}

        if "intent" in block:
            intent = Intent.from_dict(block["intent"])
            prior = self.service.store.get_receipt(intent.intent_id) or (
                self.service.store.committed_for_digest(intent.chain_id, intent.digest)
            )
            replay = bool(block.get("replay", False))
            if (
                replay
                and prior is None
                and decide(
                    Evidence(
                        nondeterministic_replay=self.nondeterministic
                        or bool(block.get("nondeterministic")),
                    )
                )
                is Action.QUARANTINE
            ):
                await event_queue.enqueue_event(
                    reply("replay quarantined", {"status": "quarantine"}, context)
                )
                return
            try:
                if self.before_execute:
                    self.before_execute(intent, text)
                if hasattr(self.tool, "execute_intent"):
                    state, receipt = self.tool.execute_intent(intent, text, self.service)
                else:
                    state, receipt = self.service.execute_effect(
                        intent, lambda: self.tool.apply(text)
                    )
            except (ValueError, StoreConflict) as exc:
                await event_queue.enqueue_event(
                    reply(
                        "request quarantined", {"status": "quarantine", "reason": str(exc)}, context
                    )
                )
                return
            if receipt is None:
                await event_queue.enqueue_event(
                    reply("outcome unresolved", {"status": "quarantine"}, context)
                )
                return
            if self.after_commit:
                self.after_commit(intent, receipt)
            out["status"] = state
            out["receipt"] = receipt.to_dict()
            out["checkpoint"] = self.service.store.export_checkpoint(
                self.service.priv, self.service.org, intent.chain_id
            ).to_dict()
            if self.downstream_url and receipt.status == "committed":
                out["downstream"] = await self._delegate(text, intent.chain_id, receipt.hash)
                if out["downstream"].get("status") == "quarantine":
                    out["status"] = "quarantine"
        else:
            self.tool.apply(text)
            if self.downstream_url:
                out["downstream"] = await self._delegate(text, None, None)

        if self.on_result and "intent" in block:
            self.on_result(intent, out)
        await event_queue.enqueue_event(reply(f"{self.name} done", out or None, context))

    async def _delegate(self, text: str, chain_id: str | None, parent_hash: str | None) -> dict:
        from recovery.a2a_client import send_message
        from recovery.a2a_middleware import EXTENSION_URI
        from recovery.crypto import public_key_from_hex

        async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
            pub = None
            org = None
            if chain_id is not None:
                response = await http.get(
                    self.downstream_url.rstrip("/") + "/.well-known/agent-card.json"
                )
                response.raise_for_status()
                for extension in response.json().get("capabilities", {}).get("extensions", []):
                    if extension.get("uri") == EXTENSION_URI:
                        params = extension.get("params", {})
                        org = params.get("org")
                        if org not in self.peer_keys and self.discover_demo_keys:
                            self.peer_keys[org] = public_key_from_hex(params["public_key"])
                        pub = self.peer_keys.get(org)
                if pub is None:
                    return {"status": "quarantine", "reason": "downstream key is not pinned"}
                digest = (
                    self.downstream_digest(text)
                    if self.downstream_digest
                    else compute_digest(self.action_type, "downstream", {"task": text})
                )
                proposed = make_intent(chain_id, digest, parent_receipt=parent_hash)
                saved = self.service.store.put_plan(
                    chain_id,
                    "delegate:" + self.downstream_url,
                    {"intent": proposed.to_dict(), "text": text},
                )
                intent = Intent.from_dict(saved["intent"])
                # Retry a stored delegation exactly, rather than invoke an LLM again.
                text = saved["text"]
            else:
                intent = None
            result = await send_message(
                self.downstream_url,
                text,
                intent,
                http,
                pub=pub,
                retry_url=self.downstream_retry_url,
                metadata={"nondeterministic": self.nondeterministic},
            )
            if chain_id is not None and result.get("status") in ("done", "proceed"):
                raw = result.get("checkpoint")
                if raw is None:
                    return {"status": "quarantine", "reason": "missing checkpoint"}
                try:
                    cp = Checkpoint.from_dict(raw)
                except (ValueError, TypeError, KeyError):
                    return {"status": "quarantine", "reason": "malformed checkpoint"}
                if cp.org_id != org or cp.chain_id != chain_id:
                    return {"status": "quarantine", "reason": "checkpoint binding mismatch"}
                check = reconcile_cut(self.service.store, {org: cp}, {org: pub})
                if check.conflicts or check.missing_at:
                    return {"status": "quarantine", "reason": "checkpoint conflict"}
            return result

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError
