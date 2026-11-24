# Ledgerless combined repository

One source tree combining the original Ledgerless repository with its signed
checkpoint extension, five runnable domain use cases, and a one-window shared
intent-box dashboard. The original repository is
https://github.com/AdityaShome/Ledgerless. Exact merge provenance is recorded in
`MERGE_PROVENANCE.json`; no changes have been pushed upstream.

## Start the single-window solution

Requires Python 3.11 or later. No model key or external service account is needed.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux or macOS instead:
# source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m dashboard.app
```

Open **http://127.0.0.1:8080**. Select a use case and fault, edit the initial
guidelines and common specification, and click **Run A → B → C**. All agents read
the same specification and append signed, versioned updates to the visible intent
box. Their private recovery stores remain independent. Run one dashboard process
with one worker. See [the context design](docs/SHARED_CONTEXT.md).

## Runnable use cases

Payments and commerce; supply chain/logistics; healthcare/insurance; enterprise
agent marketplaces/cloud provisioning; travel booking. Each has a minimal JSON
fixture and three organizations, using one shared executor implementation.

```bash
python -m examples.run_use_cases --case all --fault clean
python -m examples.run_use_cases --case all --fault lost_response
python -m bench.http_use_cases --case all --fault all --output results/http_use_cases.json
```

See [use cases and failure modes](docs/USE_CASES.md).

## Recovery protocol

1. Before an effect, declare a semantic digest intent in A2A `x-recovery` metadata.
2. After commitment, exchange an Ed25519-signed receipt linked to its predecessor.
3. Resolve uncertain effects with `recovery/resolveIntent`: committed, tombstone,
   or unknown. Binding violations quarantine rather than returning another task's evidence.
4. Exchange signed versioned checkpoints through `recovery/queryCut`; detect stale
   state, conflicts, missing peers, and missing predecessor receipts.
5. Preserve downstream plans on re-drive. Quarantine unguarded changed-action replay.

| Evidence | Decision |
|---|---|
| Valid committed receipt | Resume past the effect |
| Valid tombstone | Replay with a new intent ID, subject to replay guards |
| Declared intent, no receipt, reachable peer | Resolve and decide again |
| Unreachable or unknown past the recovery budget | Quarantine |
| Committed receipt and upstream abort | Compensate through a supported idempotent tool |
| Invalid receipt signature | Quarantine and alert |

A single UI context is not a globally readable private task log. This sandbox
runs separate A2A HTTP endpoints, signing keys and replica-local SQLite stores.
Per-organization synthetic providers supply idempotency and durable outcome
lookup; that contract is essential to the strong duplicate-prevention tests.
There are no real payments, bookings, clinical actions, or cloud resources.

## Tests and experiments

```bash
python -m ruff check .
python -m pytest -q
# Original upstream simulator and RQ sweeps:
python -m bench.run all
python -m bench.metrics
# Earlier extension compatibility benchmark:
python -m bench.runner
```

The upstream simulator's existing result CSVs and figures remain historical
reference data. The new real-HTTP matrix records separate outputs and measured
local latency/bytes. Temporal/shared-history and aggressive-quarantine baseline
adapters are simulations, not claims about deployed Temporal or Agent Mesh.
The toy replanner varies request identifiers and memo fields without live LLM calls.

Research questions RQ1–RQ4 and claims C1–C4 are mapped in
[requirements and safety contracts](docs/REQUIREMENTS.md). Known failed claims
and granularity failures remain visible; quarantine is not silently counted as
successful completion. The [validation report](VALIDATION.md) records checks run
on this distribution. The retained formal models and configurations are under
`formal/`; Java and a separately obtained TLC JAR are required to rerun them.

## Layout

```text
recovery/       One canonical protocol library and shared coordination box
agents/         One A2A executor and synthetic tooling
examples/       Five JSON fixtures and executable workflows
dashboard/      One-window local application
bench/          Upstream simulator, HTTP matrix and compatibility adapters
baselines/      Explicitly labelled comparison simulations
formal/         Original and checkpoint-cut TLA+ models
tests/          Retained tests plus domain, provider and dashboard coverage
results/        Historical evidence and newly generated validation outputs
docs/           Context architecture, use cases and requirement mapping
```

No dependency caches, private keys, live databases, nested repository copies or
virtual environments belong in the ZIP. Dependency installation downloads the
packages declared in `pyproject.toml`. The original snapshot supplies no explicit
project/data licence; this distribution does not invent one.
