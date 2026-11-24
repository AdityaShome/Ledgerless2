"""Hashing, canonical JSON and Ed25519 signing. File-based keys only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, compact separators, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def public_key_hex(pub: Ed25519PublicKey) -> str:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def public_key_from_hex(h: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(h))


def save_private_key(priv: Ed25519PrivateKey, path: str | Path) -> None:
    raw = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    Path(path).write_text(raw.hex())


def load_private_key(path: str | Path) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(Path(path).read_text().strip()))


def sign(priv: Ed25519PrivateKey, message: bytes) -> str:
    return priv.sign(message).hex()


def verify(pub: Ed25519PublicKey, message: bytes, sig_hex: str) -> bool:
    try:
        pub.verify(bytes.fromhex(sig_hex), message)
    except (InvalidSignature, ValueError):
        return False
    return True
