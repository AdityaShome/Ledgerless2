"""Versioned public coordination context. Never an execution history or recovery oracle."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from recovery.crypto import canonical, sha256_hex, sign, verify


class ContextConflict(ValueError):
    pass


class IntentBox:
    def __init__(self, path: str | Path = ":memory:"):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS contexts(
                run_id TEXT PRIMARY KEY, version INTEGER, guidelines TEXT, specification TEXT,
                spec_hash TEXT, state TEXT);
            CREATE TABLE IF NOT EXISTS updates(
                run_id TEXT, version INTEGER, org TEXT, event_key TEXT, body TEXT,
                PRIMARY KEY(run_id,version), UNIQUE(run_id,org,event_key));
        """)

    def create(self, run_id, guidelines, specification):
        if not isinstance(guidelines, str) or not guidelines.strip():
            raise ValueError("initial guidelines required")
        digest = sha256_hex(canonical({"guidelines": guidelines, "specification": specification}))
        with self.lock:
            self.db.execute(
                "INSERT INTO contexts VALUES(?,1,?,?,?,?)",
                (run_id, guidelines, json.dumps(specification), digest, "created"),
            )
            self.db.commit()
        return self.snapshot(run_id)

    def snapshot(self, run_id):
        with self.lock:
            row = self.db.execute(
                "SELECT version,guidelines,specification,spec_hash,state "
                "FROM contexts WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown intent box")
            updates = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT body FROM updates WHERE run_id=? ORDER BY version", (run_id,)
                )
            ]
        return {
            "run_id": run_id,
            "version": row[0],
            "initial_guidelines": row[1],
            "specification": json.loads(row[2]),
            "spec_hash": row[3],
            "state": row[4],
            "updates": updates,
        }

    def revise(self, run_id, expected_version, guidelines, specification):
        with self.lock:
            old = self.snapshot(run_id)
            if old["version"] != expected_version or old["state"] != "created" or old["updates"]:
                raise ContextConflict("specification is frozen once execution starts")
            digest = sha256_hex(
                canonical({"guidelines": guidelines, "specification": specification})
            )
            self.db.execute(
                "UPDATE contexts SET version=version+1,guidelines=?,specification=?,"
                "spec_hash=? WHERE run_id=?",
                (guidelines, json.dumps(specification), digest, run_id),
            )
            self.db.commit()
            return self.snapshot(run_id)

    def set_state(self, run_id, state):
        with self.lock:
            self.db.execute("UPDATE contexts SET state=? WHERE run_id=?", (state, run_id))
            self.db.commit()

    def append(self, run_id, org, event_key, summary, priv, expected_version=None):
        """Idempotent signed agent contribution; initial guidelines remain immutable."""
        if not isinstance(summary, str) or len(summary) > 1000:
            raise ValueError("invalid public summary")
        with self.lock:
            old = self.db.execute(
                "SELECT body FROM updates WHERE run_id=? AND org=? AND event_key=?",
                (run_id, org, event_key),
            ).fetchone()
            if old:
                return json.loads(old[0])
            snapshot = self.snapshot(run_id)
            if expected_version is not None and expected_version != snapshot["version"]:
                raise ContextConflict("stale intent box version; reread before updating")
            if org not in [s["org"] for s in snapshot["specification"]["steps"]]:
                raise ValueError("agent not enrolled in this specification")
            event = {
                "run_id": run_id,
                "org": org,
                "version": snapshot["version"] + 1,
                "observed_version": snapshot["version"],
                "spec_hash": snapshot["spec_hash"],
                "event_key": event_key,
                "summary": summary,
                "at": datetime.now(UTC).isoformat(),
            }
            event["sig"] = sign(priv, canonical(event))
            self.db.execute(
                "INSERT INTO updates VALUES(?,?,?,?,?)",
                (run_id, event["version"], org, event_key, json.dumps(event)),
            )
            self.db.execute(
                "UPDATE contexts SET version=? WHERE run_id=?", (event["version"], run_id)
            )
            self.db.commit()
            return event

    def close(self):
        self.db.close()


def verify_update(event, pub):
    return verify(pub, canonical({k: v for k, v in event.items() if k != "sig"}), event["sig"])
