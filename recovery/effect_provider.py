"""Durable synthetic external service per organization, shared ONLY by its replicas.

Atomically applies a fake effect and signs its receipt; real tools need equivalent
idempotency/lookup/cancellation contracts. Never a cross-organization task log.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path

from recovery.receipts import Receipt, make_receipt
from recovery.store import StoreConflict


class SyntheticEffectProvider:
    def __init__(self, path: str | Path, priv):
        self.priv = priv
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS effects(chain_id TEXT, slot TEXT, digest TEXT,
                receipt TEXT, compensated INTEGER DEFAULT 0, PRIMARY KEY(chain_id,slot));
            CREATE TABLE IF NOT EXISTS bindings(intent_id TEXT PRIMARY KEY, chain_id TEXT,digest TEXT);
            CREATE TABLE IF NOT EXISTS cancelled(intent_id TEXT PRIMARY KEY,
                chain_id TEXT,digest TEXT);
        """)

    def _bind(self, chain_id, intent_id, digest):
        existing = self.db.execute(
            "SELECT chain_id,digest FROM bindings WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if existing and existing != (chain_id, digest):
            raise StoreConflict("provider intent binding conflict")
        self.db.execute(
            "INSERT OR IGNORE INTO bindings VALUES(?,?,?)", (intent_id, chain_id, digest)
        )

    def apply(self, intent, slot):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._bind(intent.chain_id, intent.intent_id, intent.digest)
            blocked = self.db.execute(
                "SELECT 1 FROM cancelled WHERE intent_id=?", (intent.intent_id,)
            ).fetchone()
            if blocked:
                raise StoreConflict("provider permanently cancelled this intent")
            row = self.db.execute(
                "SELECT digest,receipt FROM effects WHERE chain_id=? AND slot=?",
                (intent.chain_id, slot),
            ).fetchone()
            if row:
                if row[0] != intent.digest:
                    raise StoreConflict("changed action for the same logical slot")
                return Receipt.from_dict(json.loads(row[1]))
            receipt = make_receipt(
                self.priv,
                intent.intent_id,
                intent.digest,
                "committed",
                "effect-" + uuid.uuid4().hex,
                intent.parent_receipt,
            )
            self.db.execute(
                "INSERT INTO effects VALUES(?,?,?,?,0)",
                (intent.chain_id, slot, intent.digest, json.dumps(receipt.to_dict())),
            )
            return receipt

    def resolve(self, chain_id, intent_id, digest):
        """Linearizes cancellation with execution; absent in one replica is NOT enough."""
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._bind(chain_id, intent_id, digest)
            blocked = self.db.execute(
                "SELECT chain_id,digest FROM cancelled WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if blocked and blocked != (chain_id, digest):
                raise StoreConflict("provider binding conflict")
            # Validate original identity even when the caller supplies a foreign chain.
            for stored_chain, body in self.db.execute("SELECT chain_id,receipt FROM effects"):
                r = Receipt.from_dict(json.loads(body))
                if r.intent_id == intent_id and (stored_chain != chain_id or r.digest != digest):
                    raise StoreConflict("provider task belongs to a different chain")
            row = self.db.execute(
                "SELECT receipt FROM effects WHERE chain_id=? AND digest=?", (chain_id, digest)
            ).fetchone()
            if row:
                return Receipt.from_dict(json.loads(row[0]))
            self.db.execute(
                "INSERT OR IGNORE INTO cancelled VALUES(?,?,?)", (intent_id, chain_id, digest)
            )
            return make_receipt(self.priv, intent_id, digest, "tombstone", None, None)

    def compensate(self, chain_id, original):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT receipt FROM effects WHERE chain_id=? AND digest=?",
                (chain_id, original.digest),
            ).fetchone()
            if not row or Receipt.from_dict(json.loads(row[0])).hash != original.hash:
                raise StoreConflict("compensation lacks original effect evidence")
            self.db.execute(
                "UPDATE effects SET compensated=1 WHERE chain_id=? AND digest=?",
                (chain_id, original.digest),
            )
        return "compensated-" + original.effect_ref

    def counts(self, chain_id):
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*),COALESCE(SUM(compensated),0) FROM effects WHERE chain_id=?",
                (chain_id,),
            ).fetchone()
            return {"effects": row[0], "compensated": row[1]}

    def close(self):
        self.db.close()
