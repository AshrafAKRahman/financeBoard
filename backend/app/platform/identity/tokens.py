"""Opaque secrets: session cookies and invitation links.

The raw token leaves the process once, to the browser or the email. Only its SHA-256
hash is stored, so a database copy cannot be used to sign in (R4.AC2, R11.AC4).
"""

import hashlib
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    """A 32-byte URL-safe secret, safe to put in a cookie or a link."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def tokens_match(raw_token: str, stored_hash: str) -> bool:
    return secrets.compare_digest(token_hash(raw_token), stored_hash)
