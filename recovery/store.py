"""SQLite-backed local store per replica (guide 3.5).

Safety rules enforced here:
- a committed receipt is never overwritten or removed;
- an intent that is tombstoned can never be committed, and vice versa;
- every write bumps a monotonic version.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from recovery.crypto import canonical, sha256_hex
from recovery.intents import Intent
from recovery.receipts import Receipt

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v INTEGER);
CREATE TABLE IF NOT EXISTS intents(
  intent_id TEXT PRIMARY KEY, chain_id TEXT, digest TEXT, body TEXT, version INTEGER);
CREATE TABLE IF NOT EXISTS receipts(
  intent_id TEXT PRIMARY KEY, chain_id TEXT, digest TEXT, status TEXT, body TEXT, version INTEGER);
CREATE TABLE IF NOT EXISTS plans(chain_id TEXT, slot TEXT, body TEXT, PRIMARY KEY(chain_id, slot));
CREATE INDEX IF NOT EXISTS receipts_digest ON receipts(chain_id, digest, status);
"""


class StoreConflict(Exception):
    """Attempt to violate a safety rule (e.g. commit a tombstoned intent)."""


class Store:
    def __init__(self, path: str | Path = ":memory:", org_id: str | None = None):
        self.lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('version', 0)")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('checkpoint_epoch', 0)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS peer_checkpoints("
            "org TEXT, chain TEXT, body TEXT, PRIMARY KEY(org, chain))"
        )
        self.db.commit()
        if org_id is not None:
            self.set_org(org_id)

    def set_org(self, org_id):
        if not org_id or (self.org_id is not None and self.org_id != org_id):
            raise StoreConflict("store organization mismatch")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('org_id', ?)", (org_id,))
        self.db.commit()

    @property
    def checkpoint_epoch(self):
        return self.db.execute("SELECT v FROM meta WHERE k='checkpoint_epoch'").fetchone()[0]

    @property
    def org_id(self):
        row = self.db.execute("SELECT v FROM meta WHERE k='org_id'").fetchone()
        return str(row[0]) if row else None

    def snapshot(self, since_version=0):
        if type(since_version) is not int or since_version < 0:
            raise ValueError("invalid version")
        with self.lock:
            rows = self.db.execute(
                "SELECT body FROM receipts WHERE version>? ORDER BY version", (since_version,)
            ).fetchall()
            return [Receipt.from_dict(json.loads(body)) for (body,) in rows]

    def peer_checkpoint(self, org_id, chain_id):
        from recovery.checkpoint import Checkpoint

        row = self.db.execute(
            "SELECT body FROM peer_checkpoints WHERE org=? AND chain=?", (org_id, chain_id)
        ).fetchone()
        return Checkpoint.from_dict(json.loads(row[0])) if row else None

    def remember_checkpoint(self, cp):
        self.db.execute(
            "INSERT OR REPLACE INTO peer_checkpoints VALUES(?,?,?)",
            (cp.org_id, cp.chain_id, json.dumps(cp.to_dict())),
        )
        self.db.commit()

    def export_checkpoint(self, priv, org_id=None, chain_id="", include_receipts=False):
        from recovery.checkpoint import make_checkpoint

        with self.lock:
            self.set_org(org_id or self.org_id)
            state = {
                table: self.db.execute(
                    f"SELECT chain_id, body FROM {table} ORDER BY intent_id"
                ).fetchall()
                for table in ("intents", "receipts")
            }
            state["plans"] = self.db.execute(
                "SELECT chain_id,slot,body FROM plans ORDER BY chain_id,slot"
            ).fetchall()
            state_digest = sha256_hex(canonical(state))
            self.db.execute("UPDATE meta SET v=v+1 WHERE k='checkpoint_epoch'")
            self.db.commit()
            return make_checkpoint(
                priv,
                self.org_id,
                self.checkpoint_epoch,
                {self.org_id: self.version},
                chain_id,
                [r.to_dict() for _, r in self.receipts_for_chain(chain_id)]
                if include_receipts
                else [],
                state_digest=state_digest,
            )

    def binding_matches(self, chain_id, intent_id, digest):
        intent = self.get_intent(intent_id)
        if intent and (intent.chain_id != chain_id or intent.digest != digest):
            return False
        row = self.db.execute(
            "SELECT chain_id, digest FROM receipts WHERE intent_id=?", (intent_id,)
        ).fetchone()
        return row is None or row == (chain_id, digest)

    # -- versioning
    @property
    def version(self) -> int:
        return self.db.execute("SELECT v FROM meta WHERE k='version'").fetchone()[0]

    def _bump(self) -> int:
        self.db.execute("UPDATE meta SET v = v + 1 WHERE k='version'")
        return self.version

    # -- intents
    def record_intent(self, intent: Intent) -> None:
        """Durably declare an intent. Idempotent on intent_id."""
        if self.db.execute(
            "SELECT 1 FROM intents WHERE intent_id=?", (intent.intent_id,)
        ).fetchone():
            if self.get_intent(intent.intent_id) != intent:
                raise StoreConflict("intent id already bound")
            return
        if not self.binding_matches(intent.chain_id, intent.intent_id, intent.digest):
            raise StoreConflict("intent binding conflict")
        v = self._bump()
        self.db.execute(
            "INSERT INTO intents VALUES(?,?,?,?,?)",
            (intent.intent_id, intent.chain_id, intent.digest, json.dumps(intent.to_dict()), v),
        )
        self.db.commit()

    def unresolved_for_digest(self, chain_id, digest):
        row = self.db.execute(
            "SELECT i.body FROM intents i LEFT JOIN receipts r ON i.intent_id=r.intent_id "
            "WHERE i.chain_id=? AND i.digest=? AND r.intent_id IS NULL LIMIT 1",
            (chain_id, digest),
        ).fetchone()
        return Intent.from_dict(json.loads(row[0])) if row else None

    def get_intent(self, intent_id: str) -> Intent | None:
        row = self.db.execute("SELECT body FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
        return Intent.from_dict(json.loads(row[0])) if row else None

    # -- persisted downstream plans (D29): first write wins, so a re-drive reuses the same request
    def put_plan(self, chain_id: str, slot: str, plan: dict) -> dict:
        """Persist a first-write plan and include its creation in the store version."""
        with self.lock:
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO plans VALUES(?,?,?)", (chain_id, slot, json.dumps(plan))
            ).rowcount
            if inserted:
                self._bump()
            self.db.commit()
            return self.get_plan(chain_id, slot)

    def get_plan(self, chain_id: str, slot: str) -> dict | None:
        row = self.db.execute(
            "SELECT body FROM plans WHERE chain_id=? AND slot=?", (chain_id, slot)
        ).fetchone()
        return json.loads(row[0]) if row else None

    # -- receipts
    def state(self, intent_id: str) -> str | None:
        """'committed' | 'tombstone' | 'declared' | None."""
        row = self.db.execute(
            "SELECT status FROM receipts WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if row:
            return row[0]
        if self.db.execute("SELECT 1 FROM intents WHERE intent_id=?", (intent_id,)).fetchone():
            return "declared"
        return None

    def put_receipt(self, chain_id: str, receipt: Receipt) -> None:
        """Store a receipt. Idempotent for an identical receipt; conflicts raise."""
        if not self.binding_matches(chain_id, receipt.intent_id, receipt.digest):
            raise StoreConflict("receipt binding conflict")
        existing = self.get_receipt(receipt.intent_id)
        if existing is not None:
            if existing == receipt:
                return
            raise StoreConflict(f"intent {receipt.intent_id} already {existing.status}")
        if receipt.status == "committed":
            dup = self.committed_for_digest(chain_id, receipt.digest)
            if dup is not None:
                raise StoreConflict(f"digest already committed by {dup.intent_id}")
        v = self._bump()
        self.db.execute(
            "INSERT INTO receipts VALUES(?,?,?,?,?,?)",
            (
                receipt.intent_id,
                chain_id,
                receipt.digest,
                receipt.status,
                json.dumps(receipt.to_dict()),
                v,
            ),
        )
        self.db.commit()

    def get_receipt(self, intent_id: str) -> Receipt | None:
        row = self.db.execute(
            "SELECT body FROM receipts WHERE intent_id=?", (intent_id,)
        ).fetchone()
        return Receipt.from_dict(json.loads(row[0])) if row else None

    def committed_for_digest(self, chain_id: str, digest: str) -> Receipt | None:
        """Dedup lookup by (chain_id, digest), not request id."""
        row = self.db.execute(
            "SELECT body FROM receipts WHERE chain_id=? AND digest=? AND status='committed'",
            (chain_id, digest),
        ).fetchone()
        return Receipt.from_dict(json.loads(row[0])) if row else None

    def receipts_for_chain(self, chain_id: str) -> list[tuple[str, Receipt]]:
        rows = self.db.execute(
            "SELECT chain_id, body FROM receipts WHERE chain_id=? ORDER BY version", (chain_id,)
        ).fetchall()
        return [(c, Receipt.from_dict(json.loads(b))) for c, b in rows]

    # -- tombstones are signed receipts with status 'tombstone'; the store only refuses
    # to write one if the intent already committed (put_receipt enforces that).

    # -- replica reconciliation
    def merge_from(self, other: Store) -> int:
        """Union of receipts from another replica's store. Returns number added."""
        if self.org_id != other.org_id:
            raise StoreConflict("cross-org stores require signed checkpoint reconciliation")
        # Preflight all conflicts before applying the union.
        for chain_id, body in other.db.execute("SELECT chain_id, body FROM receipts"):
            receipt = Receipt.from_dict(json.loads(body))
            existing = self.get_receipt(receipt.intent_id)
            if not self.binding_matches(chain_id, receipt.intent_id, receipt.digest):
                raise StoreConflict("replica task binding conflict")
            if existing is not None and existing != receipt:
                raise StoreConflict("replica receipt conflict")
            duplicate = self.committed_for_digest(chain_id, receipt.digest)
            if receipt.status == "committed" and duplicate and duplicate != receipt:
                raise StoreConflict("replica digest conflict")
        for (body,) in other.db.execute("SELECT body FROM intents"):
            intent = Intent.from_dict(json.loads(body))
            existing = self.get_intent(intent.intent_id)
            if existing and existing != intent:
                raise StoreConflict("replica intent conflict")
        added = 0
        for chain_id, body in other.db.execute("SELECT chain_id, body FROM receipts").fetchall():
            r = Receipt.from_dict(json.loads(body))
            if self.get_receipt(r.intent_id) is None:
                self.put_receipt(chain_id, r)
                added += 1
        for (body,) in other.db.execute("SELECT body FROM intents").fetchall():
            self.record_intent(Intent.from_dict(json.loads(body)))
        return added

    def close(self) -> None:
        self.db.close()
