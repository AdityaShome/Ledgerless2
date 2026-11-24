"""Pure decision rule (guide 3.4). No I/O, no network, no LLM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from recovery.receipts import Receipt


class Action(str, Enum):
    RESUME = "resume"  # continue past the committed receipt
    REPLAY_SAFE = "replay"  # backward-compatible enum alias
    REPLAY = REPLAY_SAFE  # compatibility alias
    RESOLVE = "resolve"  # call recovery/resolveIntent, then decide again
    QUARANTINE = "quarantine"
    QUARANTINE_ALERT = "quarantine_alert"  # invalid signature
    COMPENSATE = "compensate"
    WAIT = "wait"  # not in the table: evidence incomplete, timeout not reached
    DISCARD = "discard"  # not in the table: nothing ran and upstream aborted


@dataclass(frozen=True)
class Evidence:
    receipt: Receipt | None = None
    signature_valid: bool = True  # result of verifying `receipt`; ignored if no receipt
    intent_declared: bool = False
    callee_reachable: bool = True
    timed_out: bool = False  # reachability timeout elapsed
    resolve_unknown: bool = False  # callee answered "unknown" (mid-recovery)
    nondeterministic_replay: bool = False
    replay_guard_hash: str | None = None
    expected_replay_guard_hash: str | None = None
    upstream_aborted: bool = False


def _replay(e: Evidence) -> Action:
    if e.upstream_aborted:
        return Action.DISCARD
    if e.nondeterministic_replay and not (
        e.replay_guard_hash
        and e.expected_replay_guard_hash
        and e.replay_guard_hash == e.expected_replay_guard_hash
    ):
        return Action.QUARANTINE
    return Action.REPLAY_SAFE


def decide(e: Evidence) -> Action:
    if e.receipt is not None:
        if not e.signature_valid or e.receipt.status not in ("committed", "tombstone"):
            return Action.QUARANTINE_ALERT
        if e.receipt.status == "tombstone":
            return _replay(e)
        # valid committed receipt
        return Action.COMPENSATE if e.upstream_aborted else Action.RESUME

    if not e.intent_declared:
        # nothing declared, so no effect can have run
        return _replay(e)

    # intent declared, no receipt
    if not e.callee_reachable:
        return Action.QUARANTINE if e.timed_out else Action.WAIT
    if e.resolve_unknown:
        return Action.QUARANTINE if e.timed_out else Action.WAIT
    return Action.RESOLVE
