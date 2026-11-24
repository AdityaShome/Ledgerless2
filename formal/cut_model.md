# Versioned checkpoint model

`A2ARecovery_cut.tla` extends the existing `A2ARecovery` module. It adds
monotonic per-observer cut vectors, checkpoint publication, and asynchronous
component-wise-max propagation. Publication includes the ancestors certified
by a hop's receipt chain. This finite abstraction has one logical effect per
hop, so versions range over 0..1; Python store versions are unbounded counters.

## Properties

- `CutType`: vectors have the expected domain and bounds.
- `CutConsistency`: cuts are downward closed under A -> B -> C delegation,
  and never claim a receipt that does not exist.
- `CutNeverRegresses`: every transition preserves or increases each component.
- `NoDuplicateEffectCut`: the original duplicate-effect invariant, unconditionally.
- Original `NoLostEffect` and `ReceiptChainValid` remain enabled.

Observers can temporarily disagree while messages propagate. Requiring equal
versions whenever two observers possess a receipt would incorrectly reject
ordinary asynchronous gossip. Cut propagation also cannot make an unsafe
executor safe, so duplicate prevention is not conditional on propagation.

## Assumptions and scope

The original model's assumptions still apply: honest signing, peer receipt
lookup across a logical hop's replicas, and atomic effect-plus-receipt commit.
Python's local execution lock is not an implementation of distributed peer
lookup. Real external tools need idempotency/transactional coordination; an
uncertain crash window is quarantined rather than declared safe to replay.
This model does not prove a refinement of the Python implementation, model
arbitrary task-state messages, or establish cross-organization availability.

The Python checkpoint frontier is a signed version observation. Its optional
receipt manifest permits verification of a causally closed **effect receipt
cut**. It is not a full snapshot of the SDK task stores or in-flight messages.
`ReconcileResult.causally_verified` has this narrower meaning. Empty or absent
manifests do not establish causal consistency. A signed scalar version or a
component-wise maximum alone never establishes it.

## Reproduction

Requires Java and an externally supplied `tla2tools.jar` (not vendored).
From `formal/`:

```bash
java -cp ../tools/tla2tools.jar tla2sany.SANY A2ARecovery_cut.tla
java -cp ../tools/tla2tools.jar tlc2.TLC -workers 2 -config A2ARecovery_cut.cfg A2ARecovery_cut.tla
java -cp ../tools/tla2tools.jar tlc2.TLC -workers 2 -config A2ARecovery_cut_crash.cfg A2ARecovery_cut.tla
java -cp ../tools/tla2tools.jar tlc2.TLC -workers 2 -config A2ARecovery_cut_replicas.cfg A2ARecovery_cut.tla
java -cp ../tools/tla2tools.jar tlc2.TLC -workers 2 -config A2ARecovery_cut_nointents.cfg A2ARecovery_cut.tla
```

Use SANY for syntax and semantic validation; `--syntax-only` is not required.
The no-intents configuration is a deliberate negative control and must fail.

## Checked results

TLC2 2026.11.15.002146 (rev bc1b506) / Java 21, on the supplied configurations:

| Configuration | Replicas | Request IDs per hop | Result | Generated / distinct states | Depth |
|---|---:|---:|---|---:|---:|
| cut | 1 | 1 | PASS | 11,638 / 649 | 20 |
| cut_crash | 1 | 1 | PASS | 107,917 / 5,192 | 23 |
| cut_replicas | 2 | 1 | PASS | 465,400 / 22,915 | 23 |
| cut_nointents | 2 | 1 | Expected duplicate-effect counterexample | 51 / 10 | 6 |

State counts depend on exploration order; these are bounded checks, not proofs
for arbitrary organizations, replica counts, failures, or LLM behavior.
