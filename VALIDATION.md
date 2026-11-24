# Combined distribution validation

Validated 24 November 2026 with Python 3.12, the declared A2A SDK 1.3.0,
and Java 21 for the formal-model checks.

## Executed checks

- **172 Python tests passed**, including all 148 tests retained from the two inputs.
  Added coverage includes five domains, real HTTP recovery, independent replica
  races, durable cancellation, common-context signatures, stale writes, versioned
  downstream plans, socket reservation and the dashboard API.
- **Ruff lint passed**. Python modules compiled successfully.
- **55 real HTTP domain/fault runs** completed with expected outcomes:
  **35 completed**, **5 compensated**,
  **15 quarantined**; **zero duplicate effects** and **zero
  uncompleted expected effects** in these particular post-commit fault scenarios.
  Quarantine is not counted as completed recovery. This matrix does not cover
  every crash position, service implementation, or network behavior.
- All 55 runs met the **predeclared 65,536-byte recovery-metadata budget per hop**;
  maximum observed: **6763 bytes**. The bound is a tiny-fixture test setting,
  not a universal overhead guarantee. Metadata can be nested and counted repeatedly
  as it crosses hops. Headers, discovery GETs and dashboard polling are excluded.
- A fresh ZIP extraction ran all five clean workflows successfully; imports
  were checked to resolve to the extracted source rather than the working tree.
- The release wheel built successfully. All five JSON fixtures and dashboard HTML
  were verified in the wheel. Dashboard JavaScript passed the Node syntax check.
- Dashboard API test: selected travel with custom initial guidelines, ran the chain,
  observed signed contributions from all three organizations, and received completion.
- Browser visual automation was attempted but the environment blocked Chromium's
  local Unix socket and browser downloads. No visual browser pass is claimed;
  the API, embedded JavaScript syntax and source layout were checked instead.
- SANY parsed and semantically checked the checkpoint-cut model.
- TLC passed three bounded configurations. Original peer-lookup and atomic-effect
  assumptions remain model assumptions, not a proof of the Python implementation.

| Formal configuration | Generated states | Distinct states | Result |
|---|---:|---:|---|
| A2ARecovery_cut | 11,638 | 649 | PASS |
| A2ARecovery_cut_crash | 107,917 | 5,192 | PASS |
| A2ARecovery_cut_replicas | 465,400 | 22,915 | PASS |
| A2ARecovery_cut_nointents | 51 | 10 | Expected duplicate-effect counterexample |

The final startup regression reserved all six replica sockets before starting
threads. A previous free-port probe could select the same port twice; that issue
was corrected and the full suite and HTTP matrix rerun.

## Evidence and reproduction

Raw results and logs are in `results/combined_validation/`. Upstream CSV/figure
results and earlier extension results remain historical reference data, clearly
separate from this merged-code run. No old numbers were overwritten to claim a
new result. The upstream simulator's seeded tests still check re-plan probability,
false/missed deduplication, persisted-plan behavior, and baseline weaknesses.

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -m examples.run_use_cases --case all --fault clean
python -m bench.http_use_cases --case all --fault all
python -m dashboard.app
```

Expected injected-crash stack traces in the HTTP experiment are deliberate F1
faults, not unexpected runner failures. One external AnyIO/pytest deprecation
warning is present in the test environment; it does not fail a test.

## Scope of the final solution

The shared box is a public versioned coordination surface, not a global private
execution log. Each organization has two separate replica stores and its own
idempotent synthetic external provider. The provider's durable contract makes
commit-after-effect resolution and concurrent replica execution safe in these
examples. Arbitrary non-idempotent real services need equivalent idempotency,
outcome lookup/cancellation, transaction coupling or fencing before these safety
properties can be claimed. No real-world action or live LLM was executed.

Checkpoints certify signed observations and effect-receipt predecessor closure;
they do not construct a full SDK task/in-flight-message snapshot. Read
`docs/REQUIREMENTS.md` for guarantees and unresolved research limits. C1–C4 remain
claims to be evaluated under specified conditions, not unconditional assertions.
