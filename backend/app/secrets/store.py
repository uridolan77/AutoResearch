"""AES-256-GCM encrypted secret store.

Layer 2 of the v4 secrets design:
    Layer 1: context filter (proposer never sees secret files)  -> agent.context
    Layer 2: encrypted store (this module)
    Layer 3: runtime injection into Docker --env at container spawn -> tasks.run_experiment

The app key comes from AR_SECRET_KEY (32 bytes, base64-encoded). Generate with
`ar secrets keygen`.
"""
from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.models import Secret

KEY_BYTES = 32
NONCE_BYTES = 12


class SecretError(RuntimeError):
    pass


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()


def _load_key() -> bytes:
    raw = get_settings().secret_key
    if not raw:
        raise SecretError(
            "AR_SECRET_KEY is not set. Generate one with `ar secrets keygen` "
            "and add it to your environment."
        )
    try:
        key = base64.urlsafe_b64decode(raw)
    except (ValueError, TypeError) as e:
        raise SecretError(f"AR_SECRET_KEY is not valid base64: {e}") from e
    if len(key) != KEY_BYTES:
        raise SecretError(
            f"AR_SECRET_KEY must decode to {KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    aes = AESGCM(_load_key())
    nonce = os.urandom(NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return ct, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    aes = AESGCM(_load_key())
    try:
        return aes.decrypt(nonce, ciphertext, associated_data=None).decode("utf-8")
    except InvalidTag as e:
        raise SecretError("Secret decryption failed (wrong key?)") from e


def put_secret(db: DbSession, name: str, value: str) -> Secret:
    ct, nonce = encrypt(value)
    existing = db.query(Secret).filter(Secret.name == name).one_or_none()
    if existing is not None:
        existing.ciphertext = ct
        existing.nonce = nonce
        db.commit()
        db.refresh(existing)
        return existing
    secret = Secret(name=name, ciphertext=ct, nonce=nonce)
    db.add(secret)
    db.commit()
    db.refresh(secret)
    return secret


def get_secret(db: DbSession, name: str) -> str:
    row = db.query(Secret).filter(Secret.name == name).one_or_none()
    if row is None:
        raise SecretError(f"Secret not found: {name}")
    return decrypt(row.ciphertext, row.nonce)


def list_secret_names(db: DbSession) -> list[str]:
    return [s.name for s in db.query(Secret).order_by(Secret.name).all()]


def delete_secret(db: DbSession, name: str) -> bool:
    row = db.query(Secret).filter(Secret.name == name).one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def decrypt_refs(db: DbSession, names: list[str]) -> dict[str, str]:
    """Bulk-decrypt secrets referenced by an evaluator's `secret_refs`."""
    if not names:
        return {}
    rows = db.query(Secret).filter(Secret.name.in_(names)).all()
    by_name = {r.name: r for r in rows}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise SecretError(f"Missing secrets: {', '.join(missing)}")
    return {n: decrypt(r.ciphertext, r.nonce) for n, r in by_name.items()}
