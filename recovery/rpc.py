"""recovery/resolveIntent JSON-RPC handler and client (guide 3.3)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from recovery.service import RecoveryService

METHOD = "recovery/resolveIntent"


def handle_resolve_request(service: RecoveryService, body: dict[str, Any]) -> dict[str, Any]:
    """Turn a JSON-RPC request body into a JSON-RPC response body."""
    rid = body.get("id")
    p = body.get("params") or {}
    if not isinstance(p, dict) or any(
        not isinstance(p.get(k), str) or not p[k] for k in ("chain_id", "intent_id", "digest")
    ):
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32602, "message": "chain_id, intent_id, digest required"},
        }
    try:
        result = service.resolve(p["chain_id"], p["intent_id"], p["digest"])
    except KeyError as e:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"missing {e}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


async def resolve_remote(
    url: str,
    chain_id: str,
    intent_id: str,
    digest: str,
    timeout: float = 5.0,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Call a peer's resolveIntent. Raises httpx errors if unreachable."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": METHOD,
        "params": {"chain_id": chain_id, "intent_id": intent_id, "digest": digest},
    }
    own = http is None
    client = http or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if own:
            await client.aclose()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


METHOD_CUT = "recovery/queryCut"


def handle_cut_request(service, body):
    from recovery.cut_protocol import CutResponse

    params = body.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("chain_id"), str):
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32602, "message": "chain_id required"},
        }
    cp = service.store.export_checkpoint(
        service.priv, service.org, params["chain_id"], include_receipts=True
    )
    return {"jsonrpc": "2.0", "id": body.get("id"), "result": CutResponse(cp).to_dict()}


async def query_cut_remote(url, chain_id, http):
    from recovery.cut_protocol import CutResponse

    rid = str(uuid.uuid4())
    response = await http.post(
        url,
        json={"jsonrpc": "2.0", "id": rid, "method": METHOD_CUT, "params": {"chain_id": chain_id}},
        timeout=5.0,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("id") != rid or "error" in data:
        raise ValueError("invalid cut RPC response")
    cp = CutResponse.from_dict(data["result"]).checkpoint
    if cp.chain_id != chain_id:
        raise ValueError("checkpoint chain mismatch")
    return cp
