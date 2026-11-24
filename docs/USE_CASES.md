# Five executable minimal use cases

| CLI case | A | B | C | Three synthetic actions |
|---|---|---|---|---|
| commerce | buyer | merchant | payment_processor | Submit order, accept order, charge payment |
| logistics | manufacturer | broker | carrier | Request freight, broker reservation, book freight |
| healthcare | hospital | insurer | pharmacy_benefit | Submit referral, authorize request, approve benefit |
| marketplace | enterprise | cloud_vendor | license_vendor | Request environment, provision instance, issue licence |
| travel | traveller | airline | hotel | Request itinerary, reserve flight, reserve room |

Each fixture is one small JSON file in `examples/use_cases/`. All five use the
same A2A executor and recovery library. No per-use-case copies of the protocol
exist. Parameters include only a synthetic order/booking/referral/deployment/trip
identifier and two or three relevant values. Payment amounts are integers in
this toy fixture; no gateway receives a charge. Healthcare tokens identify no
real patients. Compensation toggles a synthetic provider effect once and creates
a signed compensation receipt; it is not an actual refund or clinical reversal.

Examples:

```bash
python -m examples.run_use_cases --case all --fault clean
python -m examples.run_use_cases --case commerce --fault lost_response
python -m examples.run_use_cases --case logistics --fault replica_failover
python -m examples.run_use_cases --case healthcare --fault changed_action
python -m examples.run_use_cases --case marketplace --fault upstream_abort
python -m examples.run_use_cases --case travel --fault forged_receipt
```

## HTTP fault coverage

- `crash_after_commit`: B commits its effect/receipt, then fails before delegating.
  A resolves the outcome and re-drives the persisted delegation; C still executes.
- `lost_response`: B completes but its HTTP response is replaced with an error.
  The caller obtains signed commit evidence before resuming.
- `duplicate_delivery`: the same root intent is submitted twice.
- `replica_failover`: B's primary becomes unavailable after commitment; its second
  replica resolves through the same organization's durable provider, not A's logs.
- `replan_same_effect`: the root is retried with a new intent ID and unchanged
  semantic digest. No second effect occurs.
- `transient_partition`: one recovery query is blocked before resolution succeeds.
- `permanent_partition`: the uncertain peer stays unreachable; the chain quarantines.
- `forged_receipt`: the wire receipt is modified without a new valid signature;
  recovery quarantines and propagates an alert.
- `upstream_abort`: committed effects receive supported, idempotent compensation.
- `changed_action`: an unguarded non-deterministic replay with a changed digest is
  refused instead of being treated as another legitimate payment/booking.

F1–F8 upstream simulator scenarios remain available independently, including
request-ID baseline failures, re-plan probability sweeps, granularity ablations,
and a simulated single-control-plane upper bound. Those are simulation results;
the HTTP matrix runs the official A2A SDK locally. Neither uses a live LLM.
