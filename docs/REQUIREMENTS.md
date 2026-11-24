# Requirement and implementation map

| Requirement | Canonical implementation | Verification |
|---|---|---|
| Write-ahead intent in x-recovery metadata | recovery/intents.py and agents/chain_agent.py | HTTP tests and existing intent tests |
| Dedup by chain and semantic digest | recovery/service.py and recovery/store.py | Concurrent replica/provider and retry tests |
| Signed hash-linked receipts | recovery/receipts.py | Crypto, cut, and HTTP tests |
| committed/tombstone/unknown resolution | recovery/rpc.py and recovery/service.py | RPC tests and durable provider cancellation test |
| Pure recovery decision table | recovery/decide.py | Original rows plus replay-guard tests |
| Signed checkpoints and queries | recovery/checkpoint.py and recovery/cut_protocol.py | Signature, epoch, missing-peer and receipt-gap tests |
| Replay guard and stable re-delegation | decide.py, shared specification validation, Store.put_plan | Changed-action demo and persisted-plan upstream tests |
| Wrong-task protection | Store.binding_matches and provider bindings | Foreign-chain tests |
| Replica divergence and reconciliation | recovery/replicas.py and same-org merge_from | Signed receipt import and independent replica race |
| Fault benchmark | bench/http_use_cases.py, upstream bench/run.py, compatibility bench/runner.py | HTTP matrix and retained simulator tests |
| Formal consistency model | formal/A2ARecovery.tla and A2ARecovery_cut.tla | Supplied TLC configurations and logs |
| Single-window mutable intent box | dashboard/app.py and recovery/intent_box.py | Dashboard API integration, signature and stale-write tests |

## Safety contract

Signed evidence is exchanged across organizations. Private execution logs are
not used by callers to decide recovery. A committed receipt is not overwritten.
A tombstoned intent ID cannot later execute in the synthetic provider, even on
another replica after restart. Replaying after a tombstone requires a new intent
ID and the same permitted action. An open intent without durable outcome evidence
stays unknown; the generic library does not invent a tombstone after a crash.

An external tool must provide idempotency, outcome lookup, and durable
cancellation (or equivalent atomic transaction/fencing guarantees) for the strong
synthetic-provider behavior. The provider demonstration atomically commits the
fake effect with signed evidence. Local process locks or receipt gossip alone
cannot stop disconnected replicas from concurrently executing a non-idempotent
real-world action. Tests verify the provider-backed contract, not impossibility
of duplicates for arbitrary external services.

A component-wise maximum is an observed frontier. Verified predecessor closure
establishes an effect-receipt cut only; the prototype does not snapshot arbitrary
SDK task state or every in-flight message. State digests detect some conflicting
histories, not general causal ancestry. Honest organizations are assumed;
signature verification is not Byzantine consensus.

## Research questions and claims

RQ1 and RQ4 are exercised by the retained seeded simulator sweeps, including the
known fine-digest re-delegation failure and persisted-plan correction. RQ2 is
checked by both simulator and real HTTP fault tests under their stated contracts.
RQ3 has actual local elapsed time including execution, checkpoint gathering and
compensation (server startup excluded), request/response count, JSON-body bytes,
and recovery metadata bytes per hop. Counts include request plus response and
exclude HTTP headers, agent-card discovery GETs, and UI polling. JSON serialization
of nested evidence can repeat bytes; the metric counts actual disclosures rather
than unique information.

C1–C4 remain claims under test. Upstream historical data is not silently relabelled
as a merged-code run. C2 completion must distinguish quarantine from lost work.
C3 refers to a shared-history simulation, not an actual Temporal deployment. The
HTTP runner declares a default 65,536-byte recovery-metadata budget per hop before
its tiny-fixture run; C4 can only be evaluated against that explicit local budget,
not a general production overhead bound. Real LLM semantic variation and broader
network topologies require further experiments.
