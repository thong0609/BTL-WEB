"""Refresh Token helpers for the Identity service.

A refresh token is an opaque random string. Only its SHA-256 hash is stored
(``refresh_sessions.token_hash``, 64 lowercase hex characters); the token itself exists
only in the HttpOnly cookie. This module has no database or HTTP code: it generates
tokens, hashes them, and computes the two expiry times of IDN-08 (idle 7 days, absolute
30 days from login). Rotation, reuse detection and cookies live elsewhere.

A plain hash is enough here because the token is 256 bits of randomness: there is
nothing to brute-force, so no salt or slow hash is needed, and the lookup by hash can
use the unique index directly.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

REFRESH_TOKEN_BYTES: Final = 32
IDLE_TTL: Final = timedelta(days=7)
ABSOLUTE_TTL: Final = timedelta(days=30)

# token_urlsafe(32) always yields exactly 43 characters of the URL-safe alphabet.
_TOKEN_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{43}")


class MalformedRefreshTokenError(ValueError):
    """The value cannot be a refresh token this service issued."""


@dataclass(frozen=True, slots=True)
class NewRefreshToken:
    token: str = field(repr=False)
    token_hash: str


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest of the token, as stored in ``refresh_sessions.token_hash``.

    The token comes from a cookie, so it is untrusted: anything that is not exactly the
    shape this service issues raises MalformedRefreshTokenError before it is hashed, and
    the caller should answer 401 without touching the database.
    """
    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise MalformedRefreshTokenError("Malformed refresh token")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_refresh_token() -> NewRefreshToken:
    token = generate_refresh_token()
    return NewRefreshToken(token=token, token_hash=hash_refresh_token(token))


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")


def family_expires_at(now: datetime) -> datetime:
    """Absolute expiry of a new login's token family (``family_expires_at``)."""
    _require_aware(now)
    return now + ABSOLUTE_TTL


def idle_expires_at(now: datetime, family_expires_at: datetime) -> datetime:
    """Expiry of one token (``expires_at``): min(now + 7 days, family_expires_at).

    This never exceeds the family expiry, which is what the database CHECK
    ``expires_at <= family_expires_at`` requires. If the family has already expired the
    result is in the past, so the caller must check the family expiry first.
    """
    _require_aware(now)
    _require_aware(family_expires_at)
    return min(now + IDLE_TTL, family_expires_at)
