# TLC Results

TLC 2.19, Java 17. Bounds: agents A,B,C; 2 replicas; MaxReq = 2 request ids per hop. Run from `formal/`:

    java -cp ../tools/tla2tools.jar tlc2.TLC -config <cfg> A2ARecovery.tla

| Config | Property | Result | States (generated / distinct) | Depth |
|---|---|---|---|---|
| `A2ARecovery.cfg` (intents, no crash, replica symmetry) | NoDuplicateEffect, NoLostEffect, ReceiptChainValid | PASS | 11,957,765 / 889,412 | 34 |
| `A2ARecovery_live.cfg` (intents, no crash, no symmetry) | InDoubtResolves (WF on Resolve) | PASS | 23,915,371 / 1,778,784 | 34 |
| `A2ARecovery_nointents.cfg` (request-id dedup only) | NoDuplicateEffect | VIOLATED (expected) | 49 / 21 | 7 |
| `A2ARecovery_crash.cfg` (intents, crashes on) | safety invariants | INCOMPLETE | stopped at ~42M distinct, queue not drained | 29+ |

## Counterexample without intents
Replica divergence. A's request 1 executes at replica 1 and commits a receipt there. Replica 2 has not seen it, passes its local request-id check, and executes request 1 again. `effects[A] = 2`. (Request 2 was sent but not delivered in this trace; the re-plan path is also admitted by the model.)

## Caveats
- Safety runs set `AllowCrash = FALSE`: a crash only disables actions, so it should not affect these invariants. The crash-enabled run did not complete, so this is argued, not checked.
- The first intents run (crashes on, no symmetry) aborted at 6.4M distinct states with no violation when the disk filled. Not a result.
- Symmetry is used only for the safety runs; it is unsound for temporal properties.
- Bounds are small (MaxReq = 2). Results do not cover larger request counts.
- Modelling assumptions A1-A4 are in `model.md`; in particular A2 (peer receipt lookup) is what makes the intent path safe.
