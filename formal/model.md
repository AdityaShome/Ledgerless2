# Formal Model

Spec: `A2ARecovery.tla`. Configs: `A2ARecovery.cfg` (intents on), `A2ARecovery_nointents.cfg` (baseline).

## Scope
Chain A -> B -> C. Each agent has 2 replicas with durable local stores. Each agent performs one logical effect with one digest. Re-planned requests get fresh request ids but the same digest (maximal equivalence; digest granularity, RQ4, is evaluated empirically, not here).

## Faults
| Fault | Representation |
|---|---|
| Crash | `Crash`/`Restart` per replica; stores are durable |
| Message loss | `Deliver`, `DeliverReceipt`, `Resolve` may simply never fire |
| Duplication | delivery is idempotent on a set, and a request can be re-sent with a fresh id |
| Partition | `Resolve` unavailable (no fairness assumed for safety) |
| Replica divergence | per-replica `receipts`/`declared`; no shared store |
| Non-determinism | `Send` with any fresh id after a missing receipt |

F1 (crash after effect before receipt sent) and F2 (receipt lost) coincide in this abstraction: `DeliverReceipt` never fires after the effect committed.

## Assumptions
- A1: effect and local receipt commit atomically at one replica.
- A2: with intents, a replica executing an intent consults its peers' receipts (the failover reconciliation of guide 3.5, modelled as a direct union lookup).
- A3: `Resolve` tombstones all outstanding request ids durably before answering; `Execute` refuses tombstoned ids.
- A4: no Byzantine behaviour; signatures are not modelled (F7 is covered by tests).

## Properties
- `NoDuplicateEffect`: effect counter per agent <= 1.
- `NoLostEffect`: effect counter equals the number of durable receipts.
- `ReceiptChainValid`: every `prev` is a receipt of the parent hop (None at the head).
- `InDoubtResolves` (liveness, weak fairness on `Resolve`): every sent request ends tombstoned or covered by a receipt.

## Expected outcome
With intents all properties hold. Without intents `NoDuplicateEffect` fails (second request id executes at the same or the other replica).
