> Historical extension notes from the supplied ZIP. For this merged distribution,
> use README.md, docs/REQUIREMENTS.md and VALIDATION.md.

# Ledgerless extension validation

Implemented on branch `feature/cross-org-recovery` from the GitHub repository.
The full source and patch are provided separately; nothing was pushed upstream.

- Python tests: **60 passed**, including all 34 original tests.
- Ruff lint: passed. New and modified Python files checked for formatting.
- Benchmark: 5 scenarios × 4 adapters × 10 repetitions = **200 runs**.
- Ledgerless adapter: zero duplicate effects, zero lost effects, and zero wrong-task
  recoveries across the supported scenarios; foreign-chain requests quarantined.
- Request-ID-only control: **30 duplicate effects** in lost-response recovery and
  **30 wrong-task recoveries** under a foreign-chain lookup.
- SANY syntax/semantic analysis: passed.
- TLC safety and cut properties: passed for one replica, one replica with crashes,
  and two replicas (one request ID per hop). Negative no-intents control found
  the expected duplicate effect.

Raw benchmark samples, test output, and model-checking logs are included under
`results/cross_org_extension/`. See `EXTENSION.md` for execution commands and
`formal/cut_model.md` for assumptions and state counts.

## Material limits and plan corrections

Component-wise maximum is an observed frontier. Receipt manifests permit
verification of predecessor closure for the effect cut; this does not snapshot
arbitrary A2A task-store state or messages in flight. The Python protocol does
not establish consensus between independent replicas.

A matching replay guard permits replay only where the original rule allowed it;
a committed receipt is required to resume past an effect. No supplied hash is
accepted as evidence that an effect completed. Unresolved crash windows stay
pending or quarantined. External side-effect exactly-once guarantees still
require tool idempotency or atomic coupling.

Temporal and mesh comparators are explicitly labelled in-process simulations.
The request-ID control is an adapter rather than an actual SDK benchmark. The
harness uses synthetic re-planning, not a live LLM. Latencies are local adapter
measurements; they are not end-to-end cross-organization performance claims.

The TLA+ model retains the original atomic effect/receipt and peer-lookup
assumptions. Passing bounded checks does not prove the Python implementation
implements those assumptions. Complete task-marker snapshots and partitioned
replica fencing remain separate research work.
