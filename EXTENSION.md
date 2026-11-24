> Historical extension notes from the supplied ZIP. For this merged distribution,
> use README.md, docs/REQUIREMENTS.md and VALIDATION.md.

# Cross-organization recovery extension

This branch implements signed versioned checkpoints, cross-org cut gathering,
conservative reconciliation, replay gating, local concurrency hardening, a
fault-injection harness, and a bounded TLA+ cut model.

## Run

Python 3.11+:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest tests/ -v
python -m bench.runner --repeats 10 --json benchmark.json
```

The existing HTTP chain tests run actual local A2A servers. New cut tests use
ASGI/HTTPX transports and three independently keyed stores. The benchmark uses
in-process adapters and injected delivery/acknowledgement loss; its timing
excludes network and LLM latency. JSON retains individual latency samples;
Markdown reports p50 and p95, summed duplicate/lost/wrong-task counts, and the
mean fraction of quarantined hops. Fresh chains are created for every run.

## Components

- `recovery/checkpoint.py`: signed organization identity, epoch, version vector,
  chain scope, local state digest, and optional signed receipt manifest.
- `Store`: durable organization identity, checkpoint epochs, receipt deltas,
  state commitments, saved peer high-water checkpoints, and task binding checks.
- `recovery/cut_protocol.py`: concurrent RPC gathering, signer authentication,
  stale/equivocating/regressing checkpoint rejection, expected-org gap detection,
  dependency gap detection, and optional receipt-cut verification.
- `recovery/queryCut`: ASGI dispatch and async client, with chain-scoped signed
  receipt manifests. Store counters remain organization-wide, not per chain.
- `Evidence`: nondeterministic replay requires both a candidate and a trusted
  expected guard hash to match. An opaque caller-supplied hash is insufficient.
- `Action.REPLAY_SAFE`: alias of the original `REPLAY`, preserving identity and
  serialized `"replay"` compatibility. A matching guard allows replay, not resume;
  resuming past an effect still requires a valid committed receipt.
- Chain agents attach nondeterminism metadata, return signed checkpoints, verify
  downstream checkpoints and effect receipts, and propagate quarantine status.
- `RecoveryService.execute_effect`: serializes the local begin/effect/commit
  sequence. Recovered open intents block fresh IDs for the same chain/digest.
  Foreign chain/digest resolution returns quarantine instead of disclosing or
  reusing another task's receipt.
- `merge_from`: remains a same-organization replica helper, checks conflicts
  before merging, and rejects cross-org blind unions. Cross-org reconciliation
  exchanges signed evidence, not another organization's raw database.

## Deliberate corrections to the proposed plan

1. A component-wise max is an observed frontier, not inherently a consistent
   global cut. The RPC can also provide a receipt manifest. Reconciliation checks
   its signatures and predecessor closure before setting `causally_verified`.
   This certifies only the effect-receipt cut, not arbitrary SDK task state.
2. Epochs are monotonic publication counters in a persistent store, not global
   consensus epochs. Same-org independently restored replicas can conflict and
   are rejected; no election, consensus, or fencing service is implied.
3. A trace hash match does not prove that an effect already happened. It permits
   controlled replay only when the original decision rule already allowed it.
   Declared intents with uncertain outcomes still resolve/wait/quarantine.
4. `TemporalBridgeHop` simulates a shared in-process workflow history and event.
   It is not Temporal and offers no durable crash guarantee. The mesh adapter is
   an aggressive quarantine policy simulation, not a claim about Agent Mesh.
   `default_sdk` is a request-ID-only control adapter, not a measured SDK product.
5. TLA+ checks causal closure and monotonic propagation instead of impossible
   instantaneous equality of asynchronous replica knowledge. Details and run
   results are in `formal/cut_model.md`.

## Trust and correctness boundaries

Pass `peer_keys={org: pinned_public_key, ...}` to chain executors for configured
trust. Passing an empty dictionary disables discovery and rejects unknown
signers. The default `None` retains demo compatibility through agent-card key
discovery and in-memory trust on first use; it is not authenticated enrollment.
Agent-card `cut_epoch` is a discovery-time hint; query the signed checkpoint for
current state. Never treat unsigned metadata as authorization. `reconcile_cut` verifies all
supplied checkpoint and manifest signatures against the configured trust keys.

The checkpoint RPC includes scoped receipt evidence and state commitments, not
private execution traces. It is intended for authenticated peer deployments;
this prototype has no access-control layer. The optional manifest increases
metadata disclosure and should be policy-gated in a production deployment.

Neither version vectors nor signatures prevent two isolated replicas from both
executing an external effect. Local locks protect only callers sharing a Store
object. Multiple processes/replicas require tool-level idempotency or an external
coordination/fencing mechanism. A crash between an external effect and its
receipt cannot safely be classified as nonexecution: this branch leaves that
intent unknown and refuses to repeat it. This may require operator resolution.

State digests detect different data at an identical observed version. They are
not ancestry proofs for histories with different counters. Checkpoint signatures
bind the chain scope, but individual legacy receipts do not embed chain/org IDs;
those bindings rely on the signed enclosing manifest and honest local stores.
A full consistent task snapshot still needs marker/in-flight-message tracking
and versioned SDK task-state integration. That is outside this specified
checkpoint-counter implementation.

## Benchmark interpretation

`lost_event` commits an effect then drops its acknowledgement; replay uses a
fresh intent ID with the same digest. `lost_request` separately drops delivery
before any effect occurs. Both are needed: a dedup test after an undelivered
request alone cannot demonstrate duplicate prevention. `wrong_task_recovery`
queries a committed intent using a foreign chain. `duplicate_execution` races
two local requests; it is not a partitioned-replica experiment.

The protocol adapter must pass all supported scenarios. Baseline violations are
reported as data instead of failing the runner. Quarantined undelivered work is
reported as lost/uncompleted in the mesh policy row, not silently treated as
successful execution. The bounded runs do not evaluate semantic changes to LLM
actions, fuzzy equivalence, real provider LLM traces, or production throughput.
