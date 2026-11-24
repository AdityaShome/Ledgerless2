# Decisions

- D1: Python 3.12 (anaconda) used instead of 3.11; guide requires >=3.11 and 3.12 is the only compatible install. `requires-python = ">=3.11"`.
- D2: Pinned a2a-sdk==1.3.0 (latest at 2026-11-02). Revisit in Phase 3 if the API blocks middleware-only integration.
- D3: Package dirs (recovery, agents, bench, baselines) are top-level packages in one project, matching the guide layout.
- D4: Repo root is D:\projects\Ledgerless (a2a-recovery/ subfolder flattened). Guide section 5 paths are relative to it.
- D5: Canonical JSON = sorted keys, compact separators, UTF-8 (no RFC 8785 dependency).
- D6: Receipt hash covers intent_id, digest, status, effect_ref, prev (not hash/sig); sig signs the hash string.
- D7: Digest granularity: coarse = action_type+target only; medium = per-tool listed keys; fine = all key params.
- D8: Tombstones are signed receipts with status "tombstone"; the store refuses commit-after-tombstone and tombstone-after-commit.
- D9: Store dedups on (chain_id, digest) among committed receipts; a tombstoned intent does not block a replay with a new intent_id (matches TLA+ model).
- D10: decide() adds two actions not in guide 3.4: WAIT (unreachable/unknown before timeout) and DISCARD (nothing ran or tombstoned, but upstream aborted). Invalid signature takes priority over every other rule. No intent and no receipt means no effect can have run, so REPLAY.
- D11: SDK 1.3.0 JSON-RPC dispatcher has a fixed method table (unknown method returns -32601), so recovery/resolveIntent cannot be registered inside it. Plan: wrap the SDK app in ASGI middleware that answers recovery/resolveIntent itself and forwards everything else untouched. Intents/receipts travel in Message.metadata under "x-recovery"; public keys in an AgentCard extension (AgentExtension uri+params). No SDK fork.
- D12: Added a2a-sdk[http-server] and uvicorn dependencies (Starlette is needed to serve).
- D13: Added recovery/service.py (begin/commit/abandon/resolve over a Store) alongside rpc.py; the guide's layout puts handler and client in rpc.py but the shared logic needs one home. Store opens SQLite with check_same_thread=False because the server runs in another thread; callers are serialised by the asyncio loop.
- D14: resolveIntent answers "unknown" while an intent is in flight or the service is flagged recovering; for an intent never seen, or declared but with no receipt, it durably writes a signed tombstone before answering. If the same digest is committed under a different intent id (re-plan), it answers committed with that receipt.
- D15: Delegation order matches the TLA+ model: a hop performs its own effect first, then delegates with parent_receipt = its receipt hash, so each receipt's prev is the parent hop's receipt. Responses return the receipt chain nested under x-recovery.downstream.
- D16: Assumption A1 carried into code: effect and receipt are one logical step. The toy tool does not yet model a crash between them; fault injection (Phase 4) will inject F1 as "crash after receipt written, before it is sent".
- D17: Benchmark runs in-process (bench/engine.py): the real store, service, signatures and decide() over a simulated faulty network, synchronous and seeded. HTTP (Phase 3) stays the integration check; this keeps 500+ runs per cell cheap. Systems are SystemConfig values of one engine (dedup none|request_id|digest, resolve, verify_receipts, reconcile), so baselines and ablations share all other code.
- D18: Each fault fires once at a randomly chosen victim hop (F1 crash after effect+receipt, before response; F2 response dropped; F3 duplicate delivery; F4 retries land on the other replica; F5 = response drop plus p_replan; F6 first N resolveIntent calls unreachable, N=2 transient or permanent; F7 receipt corrupted in transit).
- D19: Fan-out applies at the root only: the root delegates to `fanout` parallel chains of depth-1 hops.
- D20: A hop's first plan is deterministic (same request id and params every time). Only replays can re-plan (probability p_replan: new request id, different memo, same tool/target/amount). A re-executed hop re-delegating counts as a replay.
- D21: On timeout the caller runs resolveIntent through decide(). committed -> RESUME, implemented as re-sending the ORIGINAL request so the callee dedups and finishes its subtree; tombstone -> REPLAY with a fresh plan (may re-plan); unreachable or unknown past 3 tries -> QUARANTINE; bad signature -> QUARANTINE_ALERT. COMPENSATE is not exercised yet (needs a saga-style abort scenario, Phase 5).
- D22: Metrics are per-run: duplicates = sum(count-1) over semantic effect keys (tool, target, amount), memo excluded; missing = hops whose effect never ran; completed/quarantined/alerts reported separately. A permanent partition therefore yields zero duplicates and zero missing effects but an incomplete, quarantined run; claim C2 will be reported with that distinction rather than folded into "lost".
- D23: Baselines/ablations are SystemConfig values of the one engine (bench/systems.py registry). Ablations: ours_no_intents (signed receipts, request-id dedup, replicas reconcile, no resolve), ours_no_resolve (intents + digest, every in-doubt call quarantined), digest_only_{coarse,medium,fine} (digest dedup + blind retry), ours_{coarse,fine}.
- D24: Temporal bridge is an in-process stand-in, NOT a Temporal server: central history, stable per-position activity keys (chain/hop) so retries dedup even after re-planning, compensation from the central history, and 3 modelled control-plane messages per call. Labelled UPPER BOUND everywhere. It never verifies receipts, so it accepts forged ones.
- D25: Saga baseline is orchestrator-driven (baselines/saga_compensation.py): hops do no dedup; on timeout the orchestrator reads the hop's effect ledger directly (full view); if the channel stays down it aborts and compensates acknowledged steps in reverse.
- D26: Added scenario F8 (upstream abort after downstream effects committed) so decide()'s COMPENSATE row has a system-level test; it is not part of claim C2's F1-F6. Metric `residual` = effects still standing after compensation.
- D27: RQ4 workload (bench/granularity.py) is a separate executor-level experiment. The "right" medium policy matches the workload's true identity fields by construction; an under-specified medium (amount only) is reported alongside. It shows the shape of the trade-off, not that medium is best for real tools.
- D28: FINDING (verified by locating the duplicates, tests/test_baselines.py): with fine digests, ours still duplicates under re-planning, only at hops DOWNSTREAM of the faulted hop. resolveIntent makes the faulted hop safe, but it then re-delegates, that re-delegation is a replay that may re-plan, and a fine digest misses the dedup. Coarse/medium digests are unaffected. RESOLVED by D29. Fix considered: persist the planned downstream request with the intent so re-delegation reuses it. An earlier note in this session that ours_fine had zero duplicates was a misreading of the results table.
- D29: Persist the planned downstream request (addition beyond the guide; resolves D28). With persist_plan the delegator stores the first plan for each (chain, slot) in a durable plans table (first write wins) and every re-drive reuses it verbatim instead of re-planning, so fine digests match on re-delegation and downstream duplicates under F5 drop to zero. Cost: extra durable bytes per delegation, reported as plan_bytes; the plan holds request content, so it counts toward stored/disclosed data (Phase 6). Limit: a delegator crash before the plan is saved brings the old problem back. Modelling: the bench keeps one delegator-side plan_store per run; the intent record and wire protocol are unchanged. Run as separate systems (ours_medium_persist, ours_fine_persist) beside the unchanged ours*, so the grid shows both the weakness and the fix.
- D30: Latency is not measured (the engine is synchronous). Messages per run, p50/p95 over seeds, are reported as a proxy. Bytes are the JSON size of request params plus recovery metadata, so ratios are inflated by the tiny toy payload. No overhead bound was fixed before running, so C4 reports numbers and claims no bound.
- D31: results/*.csv hold per-cell aggregates (500 seeds each), not per-run rows, to keep files small. 'lost' = an intended effect missing AND the chain neither quarantined nor aborted; a permanent partition therefore shows 0 lost and 100% quarantined (D22).

## Combined distribution decisions

- D32: Merge upstream e5e98da6f16af09fa6853bae2ece7ca63372de05 with the supplied
  extension. Use one recovery implementation, retain upstream plan persistence,
  simulator, RQ sweeps, baselines and historical evidence. Keep the extension's
  checkpoint/replay/binding safety additions; conflicts are recorded in provenance.
- D33: The shared intent box is public coordination, not a private execution log.
  Freeze initial instructions/specification for each run; agents append signed,
  versioned, idempotent updates. Run the dashboard in one process/context.
- D34: Strong replica safety in the domain demo relies on a per-organization
  idempotent synthetic provider with atomic effect/receipt publication and durable
  intent cancellation. It is never shared across organizations. Generic unknown
  crash outcomes remain unknown instead of receiving unsafe tombstones.
- D35: Preserve signed evidence and first-write downstream plans during HTTP
  re-drive. A post-commit failure must still drive unfinished downstream work.
  New request IDs with equal semantic effects dedup; changed-action replay is
  quarantined against the immutable common specification.
- D36: A receipt cut is narrower than a complete distributed task snapshot.
  The upstream D14 assumption about tombstoning an unresolved declared intent is
  superseded by provider-confirmed cancellation or conservative unknown.
- D37: The dashboard executes deterministic synthetic agents over real local A2A
  HTTP, not a shared LLM token context. Initial guidelines are shown to every agent;
  privacy-sensitive production enrollment and access control remain outside scope.
