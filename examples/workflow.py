"""Real local A2A HTTP workflows with small fixtures and independently stored org state."""

from __future__ import annotations

import json
import re
import socket
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from agents.app import build_app, build_card, serve
from agents.chain_agent import ChainAgentExecutor
from recovery.a2a_client import send_message
from recovery.crypto import generate_keypair, public_key_hex
from recovery.cut_protocol import gather_cut, reconcile_cut
from recovery.decide import Action, Evidence, decide
from recovery.effect_provider import SyntheticEffectProvider
from recovery.intent_box import IntentBox, verify_update
from recovery.intents import DigestPolicy, Granularity, compute_digest, make_intent
from recovery.receipts import verify_receipt
from recovery.replicas import import_replica_checkpoint
from recovery.service import RecoveryService
from recovery.store import Store

CASES = ("commerce", "logistics", "healthcare", "marketplace", "travel")
FAULTS = (
    "clean",
    "crash_after_commit",
    "lost_response",
    "duplicate_delivery",
    "replica_failover",
    "replan_same_effect",
    "transient_partition",
    "permanent_partition",
    "forged_receipt",
    "upstream_abort",
    "changed_action",
)


def fixture(name):
    if name not in CASES:
        raise ValueError("unknown use case")
    return json.loads((Path(__file__).parent / "use_cases" / f"{name}.json").read_text())


def step_digest(step):
    return compute_digest(
        step["action_type"],
        step["target"],
        step["params"],
        DigestPolicy(tuple(step["semantic_keys"])),
        Granularity.MEDIUM,
    )


class WireMetrics:
    def __init__(self):
        self.hops = {}

    def record(self, org, method, request, response):
        entry = self.hops.setdefault(org, {"messages": 0, "bytes_total": 0, "recovery_bytes": 0})
        entry["messages"] += 2  # request plus response
        entry["bytes_total"] += len(request) + len(response)

        def recovery_bytes(value):
            if isinstance(value, dict):
                return sum(
                    len(json.dumps(v, separators=(",", ":")).encode())
                    if k == "x-recovery"
                    else recovery_bytes(v)
                    for k, v in value.items()
                )
            if isinstance(value, list):
                return sum(recovery_bytes(v) for v in value)
            return 0

        if method.startswith("recovery/"):
            entry["recovery_bytes"] += len(request) + len(response)
        else:
            for body in (request, response):
                try:
                    entry["recovery_bytes"] += recovery_bytes(json.loads(body))
                except (ValueError, TypeError):
                    pass


class WireASGI:
    """Inject faults in real HTTP responses, not synthetic result counters."""

    def __init__(self, app, org, metrics, fault="clean", target=False):
        self.app, self.org, self.metrics, self.fault, self.target = app, org, metrics, fault, target
        self.fired = False
        self.partitioned = False
        self.resolve_drops = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks = []
        while True:
            chunk = await receive()
            chunks.append(chunk.get("body", b""))
            if not chunk.get("more_body", False):
                break
        raw = b"".join(chunks)
        try:
            method = json.loads(raw).get("method", "")
        except ValueError:
            method = ""
        is_work = not method.startswith("recovery/")
        if self.target and self.partitioned:
            block = self.fault in ("permanent_partition", "replica_failover") or (
                self.fault == "transient_partition"
                and method == "recovery/resolveIntent"
                and self.resolve_drops < 1
            )
            if block:
                self.resolve_drops += 1
                body = b'{"error":"injected unavailable peer"}'
                self.metrics.record(self.org, method, raw, body)
                await send(
                    {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

        async def replay():
            return {"type": "http.request", "body": raw, "more_body": False}

        events = []

        async def capture(event):
            events.append(event)

        await self.app(scope, replay, capture)
        body = b"".join(e.get("body", b"") for e in events if e["type"] == "http.response.body")
        if self.target and is_work and not self.fired:
            self.fired = True
            if self.fault in (
                "lost_response",
                "transient_partition",
                "permanent_partition",
                "replica_failover",
            ):
                self.partitioned = True
                body = b'{"error":"injected lost acknowledgement"}'
                events = [
                    {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"application/json")],
                    },
                    {"type": "http.response.body", "body": body},
                ]
            elif self.fault == "forged_receipt":
                data = json.loads(body)

                def forge(value):
                    if isinstance(value, dict):
                        if "receipt" in value and isinstance(value["receipt"], dict):
                            value["receipt"]["effect_ref"] = "tampered"
                            return True
                        return any(forge(v) for v in value.values())
                    if isinstance(value, list):
                        return any(forge(v) for v in value)
                    return False

                forge(data)
                body = json.dumps(data).encode()
                events = [
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"application/json")],
                    },
                    {"type": "http.response.body", "body": body},
                ]
        self.metrics.record(self.org, method, raw, body)
        for event in events:
            await send(event)


class DomainTool:
    def __init__(self, org, box, expected_hash, run_id):
        self.org, self.box, self.expected_hash, self.run_id = org, box, expected_hash, run_id

    def validate(self, intent, text):
        payload = json.loads(text)
        snap = self.box.snapshot(payload["run_id"])
        if (
            payload["run_id"] != intent.chain_id
            or payload["run_id"] != self.run_id
            or snap["spec_hash"] != payload.get("spec_hash")
            or snap["spec_hash"] != self.expected_hash
        ):
            raise ValueError("intent box or common specification mismatch")
        step = next(s for s in snap["specification"]["steps"] if s["org"] == self.org)
        if intent.digest != step_digest(step):
            raise ValueError("changed action does not match the shared specification")
        if step["params"].get("amount", 0) > snap["specification"].get("max_amount", 1000):
            raise ValueError("shared specification amount limit exceeded")
        return snap, step

    def execute_intent(self, intent, text, service):
        snap, step = self.validate(intent, text)
        self.box.append(
            self.run_id,
            self.org,
            "read-spec",
            f"Read common specification {snap['spec_hash'][:12]} and initial guidelines.",
            service.priv,
        )
        state, receipt = service.execute_provider(intent, self.org + ":" + step["action_type"])
        if receipt and receipt.status == "committed":
            self.box.append(
                self.run_id,
                self.org,
                "effect-committed",
                f"{step['action_type']} committed; opaque reference {receipt.effect_ref}.",
                service.priv,
            )
        return state, receipt


class Workflow:
    def __init__(
        self,
        case="commerce",
        fault="clean",
        *,
        box=None,
        run_id=None,
        workdir=None,
        guidelines=None,
        specification=None,
    ):
        self.data = fixture(case)
        if fault not in FAULTS:
            raise ValueError("unknown fault")
        self.case, self.fault = case, fault
        self.run_id = run_id or uuid.uuid4().hex
        self.temporary = (
            tempfile.TemporaryDirectory(prefix="ledgerless-") if workdir is None else None
        )
        self.directory = Path(self.temporary.name if self.temporary else workdir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.own_box = box is None
        self.box = box or IntentBox(self.directory / "intent-box.sqlite")
        self.snapshot = self.box.create(
            self.run_id,
            guidelines or self.data["initial_guidelines"],
            specification or self.data["specification"],
        )
        self.steps = self.snapshot["specification"]["steps"]
        self.orgs = [s["org"] for s in self.steps]
        if any(
            not isinstance(org, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", org)
            for org in self.orgs
        ):
            raise ValueError("organization names must be safe lowercase identifiers")
        if len(self.steps) != 3 or len(set(self.orgs)) != 3:
            raise ValueError("demo specification requires three distinct organizations")
        self.keys = {org: generate_keypair() for org in self.orgs}
        self.metrics = WireMetrics()
        self.providers = {}
        self.services = {}
        self.servers = []
        self.urls = {}
        self.wrappers = {}
        self.sockets = {}
        for org in self.orgs:
            for replica in range(2):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", 0))
                self.sockets[org, replica] = sock
        self.ports = {key: sock.getsockname()[1] for key, sock in self.sockets.items()}
        self.urls = {key: f"http://127.0.0.1:{port}" for key, port in self.ports.items()}
        self.started = False

    def start(self):
        self.box.set_state(self.run_id, "running")
        pubs = {org: k[1] for org, k in self.keys.items()}
        for org in self.orgs:
            provider = SyntheticEffectProvider(
                self.directory / f"{org}-provider.sqlite", self.keys[org][0]
            )
            self.providers[org] = provider
            for replica in range(2):
                self.services[org, replica] = RecoveryService(
                    Store(self.directory / f"{org}-replica-{replica}.sqlite"),
                    self.keys[org][0],
                    org,
                    provider=provider,
                )
        try:
            for index in reversed(range(3)):
                org = self.orgs[index]
                for replica in range(2):
                    service = self.services[org, replica]
                    tool = DomainTool(org, self.box, self.snapshot["spec_hash"], self.run_id)
                    downstream = self.urls[self.orgs[index + 1], 0] if index < 2 else None
                    next_digest = (
                        (lambda text, j=index + 1: step_digest(self.steps[j]))
                        if index < 2
                        else None
                    )
                    fired = [False]

                    def after(intent, receipt, org=org, fired=fired):
                        if (
                            self.fault == "crash_after_commit"
                            and org == self.orgs[1]
                            and not fired[0]
                        ):
                            fired[0] = True
                            raise RuntimeError("injected crash after durable commit")

                    def completed(intent, out, service=service, org=org):
                        state = (
                            "quarantined"
                            if out.get("status") == "quarantine"
                            else "delegation complete"
                        )
                        self.box.append(
                            self.run_id, org, "hop-result", f"{org}: {state}.", service.priv
                        )

                    executor = ChainAgentExecutor(
                        org,
                        service,
                        tool,
                        downstream,
                        peer_keys=pubs,
                        downstream_digest=next_digest,
                        downstream_retry_url=(
                            self.urls[self.orgs[index + 1], 1]
                            if index < 2 and self.fault == "replica_failover"
                            else None
                        ),
                        after_commit=after,
                        on_result=completed,
                    )
                    card = build_card(org, self.urls[org, replica], service, True)
                    app = build_app(executor, card, service)
                    wrapper = WireASGI(
                        app, org, self.metrics, self.fault, target=(index == 1 and replica == 0)
                    )
                    self.wrappers[org, replica] = wrapper
                    self.servers.append(
                        serve(wrapper, self.ports[org, replica], self.sockets[org, replica])
                    )
        except BaseException:
            self.close()
            raise
        self.started = True
        return self

    async def run(self):
        if not self.started:
            self.start()
        payload = json.dumps({"run_id": self.run_id, "spec_hash": self.snapshot["spec_hash"]})
        intent = make_intent(self.run_id, step_digest(self.steps[0]))
        start = time.perf_counter()
        async with httpx.AsyncClient(trust_env=False, timeout=15) as http:
            result = await send_message(
                self.urls[self.orgs[0], 0], payload, intent, http, pub=self.keys[self.orgs[0]][1]
            )
            if self.fault in ("duplicate_delivery", "replan_same_effect"):
                repeated = (
                    intent
                    if self.fault == "duplicate_delivery"
                    else make_intent(self.run_id, intent.digest)
                )
                result = await send_message(
                    self.urls[self.orgs[0], 0],
                    payload,
                    repeated,
                    http,
                    pub=self.keys[self.orgs[0]][1],
                    metadata={"replay": True, "nondeterministic": True},
                )
            elif self.fault == "changed_action":
                changed = make_intent(
                    self.run_id, compute_digest("different_payment", "other", {"amount": 999})
                )
                result = await send_message(
                    self.urls[self.orgs[0], 0],
                    payload,
                    changed,
                    http,
                    pub=self.keys[self.orgs[0]][1],
                    metadata={"replay": True, "nondeterministic": True},
                )
            elapsed = (time.perf_counter() - start) * 1000
            active = {
                org: (1 if self.fault == "replica_failover" and i == 1 else 0)
                for i, org in enumerate(self.orgs)
            }
            cut_info = {"verified": False, "missing": [], "conflicts": []}
            if result.get("status") != "quarantine":
                cps = await gather_cut(
                    [self.urls[org, active[org]] for org in self.orgs], self.run_id, http
                )
                observer = Store(org_id="observer")
                try:
                    checked = reconcile_cut(observer, cps, {o: self.keys[o][1] for o in self.orgs})
                    cut_info = {
                        "verified": checked.causally_verified,
                        "missing": checked.missing_at,
                        "conflicts": checked.conflicts,
                        "frontier": checked.dominant_cut,
                    }
                finally:
                    observer.close()
            counts = {org: self.providers[org].counts(self.run_id) for org in self.orgs}
            compensation = []
            compensation_allowed = self.snapshot["specification"].get("allow_compensation", True)
            if self.fault == "upstream_abort" and compensation_allowed:
                for org in reversed(self.orgs):
                    service = self.services[org, active[org]]
                    receipts = [
                        r
                        for _, r in service.store.receipts_for_chain(self.run_id)
                        if r.status == "committed"
                    ]
                    original = receipts[0]
                    if (
                        decide(
                            Evidence(
                                receipt=original,
                                signature_valid=verify_receipt(original, self.keys[org][1]),
                                upstream_aborted=True,
                            )
                        )
                        is Action.COMPENSATE
                    ):
                        ci = make_intent(
                            self.run_id,
                            compute_digest("compensate", org, {"original": original.hash}),
                            original.hash,
                        )
                        _, cr = service.execute_effect(
                            ci,
                            lambda org=org, r=original: self.providers[org].compensate(
                                self.run_id, r
                            ),
                        )
                        compensation.append(cr.to_dict())
                        self.box.append(
                            self.run_id,
                            org,
                            "compensated",
                            "Supported synthetic effect compensation completed.",
                            service.priv,
                        )
                counts = {org: self.providers[org].counts(self.run_id) for org in self.orgs}
            replica_imports = {}
            for org in self.orgs:
                source = self.services[org, active[org]]
                dest = self.services[org, 1 - active[org]]
                cp = source.store.export_checkpoint(
                    source.priv, chain_id=self.run_id, include_receipts=True
                )
                replica_imports[org] = import_replica_checkpoint(dest, cp, self.keys[org][1])
        complete = result.get("status") != "quarantine" and all(
            c["effects"] == 1 for c in counts.values()
        )
        if self.fault == "upstream_abort":
            status = "compensated" if compensation_allowed else "quarantine"
        else:
            status = "completed" if complete and cut_info["verified"] else "quarantine"
        self.box.set_state(self.run_id, status)
        snapshot = self.box.snapshot(self.run_id)
        return {
            "use_case": self.case,
            "fault": self.fault,
            "run_id": self.run_id,
            "status": status,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
            "execution_ms": round(elapsed, 3),
            "counts": counts,
            "duplicate_effects": sum(max(0, c["effects"] - 1) for c in counts.values()),
            "uncompleted_effects": sum(c["effects"] == 0 for c in counts.values()),
            "cut": cut_info,
            "wire_metrics": self.metrics.hops,
            "replica_receipts_imported": replica_imports,
            "compensation_receipts": compensation,
            "agent_response": result,
            "context": snapshot,
            "context_updates_verified": all(
                verify_update(e, self.keys[e["org"]][1]) for e in snapshot["updates"]
            ),
            "public_keys": {o: public_key_hex(self.keys[o][1]) for o in self.orgs},
        }

    def close(self):
        for server in reversed(self.servers):
            server.stop()
        for sock in self.sockets.values():
            sock.close()
        for service in self.services.values():
            service.store.close()
        for provider in self.providers.values():
            provider.close()
        if self.own_box:
            self.box.close()
        if self.temporary:
            self.temporary.cleanup()


async def run_case(case="commerce", fault="clean", **kwargs):
    workflow = Workflow(case, fault, **kwargs)
    try:
        return await workflow.run()
    finally:
        workflow.close()
