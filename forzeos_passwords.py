"""Password hashing helpers for ForzeOS accounts.

Uses bcrypt when installed. A versioned PBKDF2-HMAC-SHA256 encoding keeps
first-run setup functional in minimal installations without third-party crypto
packages. Legacy MD5 hashes are verification-only for existing installations.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

try:
    import bcrypt as _bcrypt
except Exception:
    _bcrypt = None

PBKDF2_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
_MIN_ACCEPTED_ITERATIONS = 100_000
_MAX_ACCEPTED_ITERATIONS = 2_000_000


def bcrypt_available() -> bool:
    return _bcrypt is not None


def hash_password(password: str) -> str:
    """Return a salted bcrypt or PBKDF2 hash; never store the plaintext."""
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    password_bytes = password.encode("utf-8")

    if _bcrypt is not None and len(password_bytes) <= 72:
        try:
            return _bcrypt.hashpw(password_bytes, _bcrypt.gensalt()).decode("ascii")
        except Exception:
            # Keep account creation available if an optional bcrypt backend is
            # present but fails at runtime; PBKDF2 is provided by the stdlib.
            pass

    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password_bytes, salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_SCHEME}${PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify bcrypt, versioned PBKDF2, or legacy MD5 account hashes."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False

    password_bytes = password.encode("utf-8")
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        if _bcrypt is None:
            return False
        try:
            return bool(_bcrypt.checkpw(password_bytes, stored_hash.encode("ascii")))
        except (ValueError, TypeError, UnicodeError):
            return False

    if stored_hash.startswith(PBKDF2_SCHEME + "$"):
        try:
            scheme, iterations_text, salt_hex, digest_hex = stored_hash.split("$", 3)
            if scheme != PBKDF2_SCHEME:
                return False
            iterations = int(iterations_text)
            if not _MIN_ACCEPTED_ITERATIONS <= iterations <= _MAX_ACCEPTED_ITERATIONS:
                return False
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            if len(salt) != 16 or len(expected) != 32:
                return False
            actual = hashlib.pbkdf2_hmac("sha256", password_bytes, salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    # Backward compatibility: old installations stored lowercase MD5 hex.
    legacy = hashlib.md5(password_bytes).hexdigest()
    return hmac.compare_digest(legacy, stored_hash.lower())


def password_hash_needs_upgrade(stored_hash: str) -> bool:
    """Return whether a verified legacy MD5 hash can be upgraded to bcrypt."""
    if not isinstance(stored_hash, str):
        return False
    return bcrypt_available() and not stored_hash.startswith(("$2a$", "$2b$", "$2y$", PBKDF2_SCHEME + "$"))
