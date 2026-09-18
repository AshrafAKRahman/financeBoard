"""Argon2id hashing behind one seam.

Nothing else in the codebase touches the hashing library, so parameters and the
constant-work login path live in exactly one place.
"""

from contextlib import suppress

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.shared.errors import DomainError

MIN_PASSWORD_LENGTH = 12

# 64 MiB, 3 passes, 4 lanes — OWASP's current Argon2id guidance, pinned here so
# `needs_rehash` can tell an older hash apart from a current one.
_hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)

# A real hash of a value nobody knows, verified when an email address is unknown so that
# login takes the same work either way and cannot be probed by timing (R3.AC8).
_DUMMY_HASH = _hasher.hash("bb7f4fd1b3e7c0d2a4c9f6e1a8d5b2c7")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise DomainError(
            "identity.weak_password",
            f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """False for a wrong password and for a hash we cannot read, so the caller answers
    `identity.invalid_credentials` either way (R2.AC5)."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy() -> None:
    """Spend the same work as a real verification when there is no user to check."""
    with suppress(VerifyMismatchError, VerificationError, InvalidHashError):
        _hasher.verify(_DUMMY_HASH, "")


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False
