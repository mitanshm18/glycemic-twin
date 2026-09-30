"""Passwords (Argon2id) and opaque session tokens.

Argon2id parameters follow RFC 9106's second recommended option (t=3, p=4, m=64 MiB) and are stored
in the PHC string, so they can be raised later without invalidating existing hashes. Session and
CSRF tokens are 256-bit random values; the database stores only their SHA-256.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

ARGON2_LENGTH, ARGON2_ITERATIONS, ARGON2_LANES, ARGON2_MEMORY_KIB = 32, 3, 4, 64 * 1024
MIN_PASSWORD_LENGTH = 12
_DUMMY_HASH: str | None = None
# Each Argon2id call needs 64 MiB. Unbounded, a burst of simultaneous sign-ins (or a password
# guessing burst) could exhaust memory and fail with MemoryError (a 500). At most this many run at
# once; the rest wait their turn, which also slows guessing without changing any result.
MAX_CONCURRENT_HASHES = 2
_hash_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must have at least {MIN_PASSWORD_LENGTH} characters")
    kdf = Argon2id(
        salt=os.urandom(16),
        length=ARGON2_LENGTH,
        iterations=ARGON2_ITERATIONS,
        lanes=ARGON2_LANES,
        memory_cost=ARGON2_MEMORY_KIB,
    )
    with _hash_slots:
        return kdf.derive_phc_encoded(password.encode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        with _hash_slots:
            Argon2id.verify_phc_encoded(password.encode(), encoded)
    except (InvalidKey, ValueError):
        return False
    return True


def burn_verification_time(password: str) -> None:
    """Spend the same time as a real check when the username does not exist (no user enumeration)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _DUMMY_HASH)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
