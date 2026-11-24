"""Baseline 4: Temporal-style durable execution. UPPER BOUND: assumes one control plane.

This is an in-process stand-in, not a Temporal server. It models what makes Temporal correct
here: a central durable history, and stable per-position activity keys (chain/hop), so a retry
dedups at the executor even if the agent re-plans the request. Control-plane cost is modelled as
a fixed number of history-write messages per call (SystemConfig.events_per_call).
Label it "upper bound (single control plane)" in every table.
"""

from bench.engine import TEMPORAL as CONFIG

__all__ = ["CONFIG"]
