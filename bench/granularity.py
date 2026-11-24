"""RQ4: intent-digest granularity vs false dedup and missed dedup.

Workload (one executor, real RecoveryService + Store). Each logical effect has a target and an
amount drawn from small pools (so collisions happen) and a unique `invoice` that is part of its
real identity. A re-planned duplicate of an effect changes only the wording (`memo`).

  false dedup  = a legitimate, distinct effect blocked because its digest matched an earlier one
  missed dedup = a re-planned duplicate that executed because its digest differed

Which fields count as "semantic" is a modelling choice, so two medium policies are reported:
  medium_right  keys = (amount, invoice): matches the workload's true identity
  medium_amount keys = (amount,): under-specified, ignores the invoice
The "right" policy matching the workload is by construction; the result shows the trade-off
shape, not that any one granularity is best for real tools.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from recovery.crypto import generate_keypair
from recovery.intents import DigestPolicy, Granularity, compute_digest, make_intent
from recovery.service import RecoveryService
from recovery.store import Store

POLICIES = {
    "coarse": (Granularity.COARSE, DigestPolicy()),
    "medium_amount": (Granularity.MEDIUM, DigestPolicy(medium_keys=("amount",))),
    "medium_right": (Granularity.MEDIUM, DigestPolicy(medium_keys=("amount", "invoice"))),
    "fine": (Granularity.FINE, DigestPolicy()),
}


@dataclass
class GranularityResult:
    policy: str
    legit: int
    false_dedup: int
    replans: int
    missed_dedup: int

    @property
    def false_dedup_rate(self) -> float:
        return self.false_dedup / self.legit if self.legit else 0.0

    @property
    def missed_dedup_rate(self) -> float:
        return self.missed_dedup / self.replans if self.replans else 0.0


def run_granularity(
    policy_name: str,
    seed: int,
    n_effects: int = 200,
    p_replan: float = 0.5,
    group: int = 5,
    n_targets: int = 3,
    n_amounts: int = 3,
) -> GranularityResult:
    level, policy = POLICIES[policy_name]
    rng = random.Random(seed)
    priv, _ = generate_keypair()
    svc = RecoveryService(Store(), priv, "exec")
    legit = false_dedup = replans = missed = 0

    def send(chain: str, params: dict, req_id: str) -> str:
        digest = compute_digest("charge", params["target"], params, policy, level)
        state, _ = svc.begin(make_intent(chain, digest, intent_id=req_id))
        if state == "proceed":
            svc.commit(
                make_intent(chain, digest, intent_id=req_id), f"ref-{req_id}", None
            )
        return state

    for i in range(n_effects):
        chain = f"c{i // group}"  # dedup scope: effects in the same chain can collide
        params = {
            "target": f"t{rng.randrange(n_targets)}",
            "amount": 10 * (1 + rng.randrange(n_amounts)),
            "invoice": f"inv-{i}",
            "memo": "m0",
        }
        legit += 1
        if send(chain, params, f"e{i}") == "done":
            false_dedup += 1
            continue  # the effect that was blocked never ran; a replan of it is moot
        if rng.random() < p_replan:
            replans += 1
            again = dict(params, memo=f"m{1 + rng.randrange(5)}")
            if send(chain, again, f"e{i}-replan") == "proceed":
                missed += 1
    return GranularityResult(policy_name, legit, false_dedup, replans, missed)
