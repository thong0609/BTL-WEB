"""Authenticated encryption for the short-lived Google sign-in cookies.

Two cookies carry server-side state through the browser: ``googleOAuth`` (state,
nonce, PKCE code verifier, ...) and ``googleLinkTicket`` (proof that the user just
re-entered their password). Both must be unreadable and unforgeable, and neither may
be replayable under the other's name.

Each value is ``base64url(nonce || AES-256-GCM(ciphertext + tag))`` without padding.
The nonce is 12 fresh random bytes per value. The cookie name is the associated data,
so a value sealed for one cookie fails authentication under another name. The expiry
(``exp``, epoch seconds) is inside the encrypted JSON and checked after decryption.

The key is loaded from configuration by the caller (``OAUTH_COOKIE_SECRET``, the
base64url encoding of 32 random bytes); this module takes the key as an argument.
"""

import base64
import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

OAUTH_COOKIE_NAME: Final = "googleOAuth"
LINK_TICKET_COOKIE_NAME: Final = "googleLinkTicket"
OAUTH_COOKIE_TTL: Final = timedelta(minutes=10)
LINK_TICKET_TTL: Final = timedelta(minutes=5)
KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
MAX_COOKIE_VALUE_LENGTH: Final = 4000

_EXPIRY_KEY: Final = "exp"
# 32 bytes in base64url are 43 characters; one trailing "=" is tolerated.
_SECRET_PATTERN: Final = re.compile(r"([A-Za-z0-9_-]{43})=?")


class InvalidCookieError(Exception):
    """The cookie value is malformed, forged, sealed for another cookie, or expired.

    The message is generic on purpose; the original error, if any, is ``__cause__``.
    """

    def __init__(self) -> None:
        super().__init__("Invalid cookie")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def load_cookie_key(secret: str) -> bytes:
    """Decode ``OAUTH_COOKIE_SECRET`` (base64url of 32 bytes) into the AES key.

    Raises ``ValueError`` for anything else (hex, standard base64, wrong length,
    stray characters). The message never contains the secret.
    """
    match = _SECRET_PATTERN.fullmatch(secret)
    if match is not None:
        encoded = match.group(1)
        key = _b64decode(encoded)
        if _b64encode(key) == encoded:
            return key
    raise ValueError("OAUTH_COOKIE_SECRET must be the base64url encoding of 32 random bytes")


def _check_name(name: str) -> None:
    if not name or not name.isascii():
        raise ValueError("Cookie name must be non-empty ASCII")


class CookieCipher:
    def __init__(self, *, key: bytes, clock: Callable[[], datetime] = _utc_now) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError("Cookie key must be 32 bytes")
        self._aead = AESGCM(key)
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now

    def seal(self, name: str, payload: Mapping[str, Any], *, ttl: timedelta) -> str:
        """Encrypt ``payload`` (a JSON object) for the cookie called ``name``."""
        _check_name(name)
        if ttl < timedelta(seconds=1):
            raise ValueError("ttl must be at least one second")
        if _EXPIRY_KEY in payload:
            raise ValueError("'exp' is reserved for the cookie expiry")
        expires_at = int(self._now().timestamp()) + int(ttl.total_seconds())
        plaintext = json.dumps({**payload, _EXPIRY_KEY: expires_at}, separators=(",", ":"))
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode("utf-8"), name.encode("ascii"))
        value = _b64encode(nonce + sealed)
        if len(value) > MAX_COOKIE_VALUE_LENGTH:
            raise ValueError("Cookie value is too large")
        return value

    def unseal(self, name: str, value: str) -> dict[str, Any]:
        """Decrypt and validate a cookie value; return the payload without ``exp``.

        Raises ``InvalidCookieError`` for every failure, with one generic message.
        """
        _check_name(name)
        try:
            raw = _b64decode(value)
            # Re-encoding must give back the exact value: this rejects stray characters,
            # padding and non-canonical encodings that the lenient decoder would accept.
            if _b64encode(raw) != value:
                raise ValueError("non-canonical encoding")
            nonce, sealed = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
            plaintext = self._aead.decrypt(nonce, sealed, name.encode("ascii"))
            body = json.loads(plaintext)
        except (ValueError, InvalidTag) as exc:
            raise InvalidCookieError from exc
        if not isinstance(body, dict):
            raise InvalidCookieError
        expires_at = body.pop(_EXPIRY_KEY, None)
        if type(expires_at) is not int:
            raise InvalidCookieError
        if self._now().timestamp() >= expires_at:
            raise InvalidCookieError
        return body
