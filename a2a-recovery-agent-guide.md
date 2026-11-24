# Agent Guide: Evidence-Based Recovery for Cross-Org A2A Delegation Chains

Working title: **Recovery Without the Log: Consistent Recovery of Cross-Organization A2A Delegation Chains under Non-Deterministic Re-Execution**

This file is the single source of truth for the agent building this project. Read it fully before writing code. When a decision is not covered here, pick the simplest option, log it in `DECISIONS.md`, and continue.

---

## 1. Problem Statement

In cross-org A2A chains (A -> B -> C), no party can read the full execution log. When a hop fails:

- The upstream agent cannot tell whether a downstream side effect committed.
- Replaying an LLM agent may choose a different action, so request-level idempotency keys do not match.
- Server replicas of one agent can hold divergent task state with no shared store.

Existing recovery (Temporal, LangGraph durable execution, SagaLLM) assumes one control plane with a readable log. We target recovery under **partial log observability** plus **non-deterministic re-execution**.

**Core idea:** recover from minimal signed commit evidence exchanged between hops, never from internal logs.

---

## 2. Research Questions

- **RQ1.** Does request-ID idempotency fail under LLM re-planning on replay? How often?
- **RQ2.** Do write-ahead intents + effect receipts eliminate duplicate and lost effects across hops?
- **RQ3.** What is the cost: latency, message overhead, bytes disclosed per hop?
- **RQ4.** How does intent-digest granularity trade false dedup vs missed dedup?

---

## 3. System Design

### 3.1 Write-Ahead Intents

Before any side effect, the executing agent declares an intent in A2A task metadata.

```json
{
  "x-recovery": {
    "intent": {
      "intent_id": "uuid",
      "chain_id": "uuid",
      "parent_receipt": "sha256 | null",
      "digest": "sha256(canonical(action_type, target, key_params))",
      "declared_at": "rfc3339"
    }
  }
}
```

- `digest` uses a canonical JSON form of only the semantically relevant fields.
- Executors dedup by `(chain_id, digest)`, not by request ID.
- Granularity of `key_params` is configurable per tool (needed for RQ4).

### 3.2 Hash-Chained Effect Receipts

After commit, the executor returns a signed receipt.

```json
{
  "x-recovery": {
    "receipt": {
      "intent_id": "uuid",
      "digest": "sha256",
      "status": "committed | tombstone",
      "effect_ref": "opaque external id",
      "prev": "sha256 of parent receipt",
      "hash": "sha256(this receipt minus sig)",
      "sig": "ed25519"
    }
  }
}
```

- Each org has its own Ed25519 key. Keys are published in the Agent Card extension field.
- `prev` links receipts into a chain. The consistent cut is the latest verifiable receipt per hop.
- `effect_ref` must not leak internal state. Opaque IDs only.

### 3.3 In-Doubt Resolution RPC

New JSON-RPC method on each agent:

```
recovery/resolveIntent
  params: { chain_id, intent_id, digest }
  result: { state: "committed" | "tombstone" | "unknown", receipt?: Receipt }
```

- `tombstone` means the callee guarantees the intent will never execute (it writes the tombstone durably before answering).
- `unknown` is allowed only if the callee itself is mid-recovery.

### 3.4 Decision Rule per Task

| Evidence state | Action |
|---|---|
| Valid receipt present | RESUME past it |
| Tombstone | REPLAY |
| Intent declared, no receipt, callee reachable | call `resolveIntent`, then apply this table again |
| Intent declared, callee unreachable past timeout | QUARANTINE |
| Receipt present, upstream aborted | COMPENSATE |
| Receipt signature invalid | QUARANTINE + alert |

Implement as a pure function `decide(evidence) -> Action`. It must be unit-testable without network.

### 3.5 Replica Consistency

- Each replica writes intents and receipts to its local store with a monotonic version.
- On replica failover, the new replica reconciles by taking the union of receipts and resolving open intents via 3.3.
- Safety property: a committed receipt is never forgotten; an intent never executes twice.

---

## 4. Formal Model (write before heavy coding)

Deliver `formal/model.md` and a TLA+ spec `formal/A2ARecovery.tla`.

- Processes: agents A, B, C, each with 2 replicas.
- Faults: crash, message loss, message duplication, partition, replica divergence.
- Non-determinism: on replay, an agent picks any action from a set; it may re-propose the same effect with different request IDs.
- Invariants:
  - `NoDuplicateEffect`: each digest commits at most once per chain.
  - `NoLostEffect`: every committed effect has a receipt reachable from the chain head after recovery.
  - `ReceiptChainValid`: every receipt's `prev` points to a valid parent.
- Liveness (under eventual reachability): every in-doubt intent resolves.

Run TLC on small bounds (3 agents, 2 replicas, depth 2). Record state counts and any counterexamples in `formal/results.md`.

---

## 5. Repository Layout

```
a2a-recovery/
  README.md
  DECISIONS.md
  formal/
    model.md
    A2ARecovery.tla
    results.md
  recovery/              # core library, Python 3.11
    intents.py
    receipts.py
    crypto.py
    decide.py
    store.py             # SQLite-backed local store per replica
    rpc.py               # resolveIntent handler + client
    a2a_middleware.py    # hooks into official a2a-python SDK
  agents/
    toy_llm_agent.py     # configurable re-planning agent
    tools/               # side-effecting fake tools with effect counters
  bench/
    faults.py
    scenarios/
    run.py
    metrics.py
  baselines/
    default_sdk.py
    request_id_dedup.py
    saga_compensation.py
    temporal_bridge/
  tests/
  results/
```

Use the official A2A Python SDK. Pin the version in `pyproject.toml`. Do not fork the SDK; add behavior through middleware and metadata only.

---

## 6. Benchmark

### 6.1 Toy World

- Fake side-effecting tools: `send_email`, `charge_payment`, `create_ticket`, `book_slot`. Each keeps a ground-truth effect counter.
- `toy_llm_agent` has a re-planning knob `p_replan` in [0, 1]: on replay, with that probability it picks a different but semantically equivalent request (new request ID, same effect).
- Also run a real-LLM mode (small open model) for a subset to confirm the toy knob is realistic. Report observed re-plan rate.

### 6.2 Fault Scenarios

| ID | Fault |
|---|---|
| F1 | Crash after effect, before receipt sent |
| F2 | Receipt message lost |
| F3 | Duplicate delivery of task message |
| F4 | Replica failover mid-task with divergent stores |
| F5 | Re-plan on replay (vary `p_replan`) |
| F6 | Cross-org partition during resolution |
| F7 | Forged or corrupted receipt |

Chains: depth 2, 3, 5. Fan-out: 1 and 3. At least 500 runs per (scenario, system, config). Fix seeds.

### 6.3 Metrics

- Duplicate effects (count from ground-truth counters)
- Lost effects
- Wrong-task recovery (resumed or compensated the wrong task)
- In-doubt rate and time to resolve
- End-to-end recovery latency (p50, p95)
- Message overhead (extra messages, extra bytes)
- Bytes disclosed per hop (privacy cost)
- False-dedup rate (legit repeat blocked) for RQ4

### 6.4 Baselines

1. Default A2A SDK behavior (retry on failure).
2. Request-ID idempotency keys.
3. SagaLLM-style compensation (single orchestrator with full view).
4. Temporal bridge: all agents in one Temporal namespace. This is the **upper bound** that cheats by assuming one control plane. Label it so in every table.

### 6.5 Ablations

- No intents (receipts only)
- No `resolveIntent` (quarantine all in-doubt)
- Intent digest granularity: coarse, medium, fine

---

## 7. Phases and Acceptance Criteria

Work in order. Do not start a phase until the previous one passes.

**Phase 0: Setup (0.5 day)**
- Repo skeleton, pinned deps, CI with pytest and ruff.
- Done when: `pytest` runs green on an empty test.

**Phase 1: Formal model (2 days)**
- `model.md` and TLA+ spec. TLC passes all invariants at small bounds.
- Done when: also show TLC finds a duplicate effect when intents are removed.

**Phase 2: Core library (3 days)**
- intents, receipts, crypto, store, `decide`.
- Done when: `decide` has a unit test for every row in 3.4, and receipt chain verification rejects tampered inputs.

**Phase 3: A2A integration (3 days)**
- Middleware + `resolveIntent` RPC on the official SDK. Three agents A -> B -> C over HTTP locally.
- Done when: a happy-path chain runs end to end, and existing A2A clients without the extension still work.

**Phase 4: Fault injection + toy agents (3 days)**
- `faults.py`, scenarios F1 to F7, effect counters.
- Done when: default SDK baseline shows nonzero duplicates on F1 and F5.

**Phase 5: Baselines (3 days)**
- All four baselines runnable under the same harness.

**Phase 6: Experiments (3 days)**
- Full grid, seeds fixed, results to `results/*.csv`, plots to `results/figs/`.
- Done when: every RQ has at least one table or figure answering it.

**Phase 7: Write-up support (2 days)**
- `results/summary.md`: key numbers, which claims are supported, which are not.

---

## 8. Claims to Test (do not assume them)

- C1: Request-ID dedup produces duplicates that grow with `p_replan`.
- C2: Our system has zero duplicate and zero lost effects on F1 to F6.
- C3: Our system matches the Temporal upper bound on correctness without a shared control plane.
- C4: Overhead stays under a stated bound (report it, do not tune to it).

If any claim fails, report it honestly in `summary.md`. Do not change metrics or scenarios to make a claim pass.

---

## 9. Related Work the Agent Must Track

Keep `related_work.md` with one paragraph per item on how we differ.

- Temporal / durable execution for LLM agents (single control plane, readable log)
- LangGraph durable execution
- SagaLLM (compensation inside one orchestrator)
- Microsoft AgentMesh (trust quarantine, not recovery)
- Durable authorization state for replay-resistant agent actions (arXiv 2608.01710)
- The April 2026 paper on non-deterministic node output and non-idempotent retry in agent workflows (find and cite)
- A2ABreak (no chain identifier in A2A)
- Strabo (A2A state machine is informally specified)
- Chandy-Lamport snapshots, 2PC in-doubt resolution, sagas (classical roots)

---

## 10. Non-Goals

- No Byzantine fault tolerance. Assume orgs may crash or lose messages but sign honestly. Forged receipts (F7) are detected, not tolerated.
- No changes to core A2A message types. Extension via metadata and one new RPC only.
- No production key management. File-based keys are fine.
- No GUI.

---

## 11. Rules for the Agent

1. Write tests before or with every module.
2. Every experiment run writes its config + seed + git commit hash next to its output.
3. Never edit result files by hand.
4. Log every design choice not in this guide in `DECISIONS.md` with one line of reasoning.
5. If a phase takes more than 2x its estimate, stop and write a blocker note in `DECISIONS.md`.
6. Keep the core library free of LLM calls. Non-determinism lives only in `agents/`.
