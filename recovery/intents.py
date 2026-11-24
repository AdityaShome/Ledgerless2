"""Write-ahead intents and intent digests (guide 3.1)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from recovery.crypto import canonical, sha256_hex


class Granularity(str, Enum):
    COARSE = "coarse"
    MEDIUM = "medium"
    FINE = "fine"


@dataclass(frozen=True)
class DigestPolicy:
    """Which key_params feed the digest, per granularity.

    coarse: only action_type + target.
    medium: the listed `medium_keys` (per tool).
    fine:   every key param.
    """

    medium_keys: tuple[str, ...] = ()

    def select(self, level: Granularity, params: dict[str, Any]) -> dict[str, Any]:
        if level is Granularity.COARSE:
            return {}
        if level is Granularity.MEDIUM:
            return {k: params[k] for k in self.medium_keys if k in params}
        return dict(params)


def compute_digest(
    action_type: str,
    target: str,
    key_params: dict[str, Any],
    policy: DigestPolicy | None = None,
    level: Granularity = Granularity.FINE,
) -> str:
    """sha256(canonical(action_type, target, key_params)) over the relevant fields only."""
    params = (policy or DigestPolicy()).select(level, key_params)
    return sha256_hex(
        canonical({"action_type": action_type, "target": target, "key_params": params})
    )


@dataclass(frozen=True)
class Intent:
    intent_id: str
    chain_id: str
    parent_receipt: str | None
    digest: str
    declared_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Intent:
        return Intent(
            intent_id=d["intent_id"],
            chain_id=d["chain_id"],
            parent_receipt=d.get("parent_receipt"),
            digest=d["digest"],
            declared_at=d["declared_at"],
        )


def make_intent(
    chain_id: str, digest: str, parent_receipt: str | None = None, intent_id: str | None = None
) -> Intent:
    return Intent(
        intent_id=intent_id or str(uuid.uuid4()),
        chain_id=chain_id,
        parent_receipt=parent_receipt,
        digest=digest,
        declared_at=datetime.now(UTC).isoformat(),
    )
