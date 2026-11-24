"""Access Token (JWT, RS256) issuing and verification for the Identity service.

The token carries only who the caller is and when it expires: ``iss``, ``sub`` (user
id), ``iat`` and ``exp``, plus the signing key id in the ``kid`` header. Role and
status are deliberately not in the token: they can change while a token is still
valid, so services read them from ``GET /api/v1/users/me``.

The private key belongs to Identity only. Loading it from configuration is the
caller's job; this module takes the key and the issuer as arguments.
"""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ALGORITHM: Final = "RS256"
ACCESS_TOKEN_TTL_SECONDS: Final = 900
MIN_RSA_KEY_BITS: Final = 2048
_REQUIRED_CLAIMS: Final = ["exp", "iat", "iss", "sub"]


class InvalidAccessTokenError(Exception):
    """The token is malformed, expired, or was not issued by this service.

    The message is generic on purpose; the original error is kept as ``__cause__``.
    """


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    token: str
    expires_in: int
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _key_id(public_key: rsa.RSAPublicKey) -> str:
    der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.urlsafe_b64encode(hashlib.sha256(der).digest()).rstrip(b"=").decode("ascii")


def load_private_key(pem: str | bytes) -> rsa.RSAPrivateKey:
    """Parse an unencrypted RSA private key in PEM form.

    Env files often hold a PEM on one line with literal ``\\n`` sequences; those are
    expanded. Raises ValueError for anything that is not a usable RSA key. The error
    text never includes key material.
    """
    data = pem.encode("utf-8") if isinstance(pem, str) else pem
    if b"\\n" in data and b"\n" not in data:
        data = data.replace(b"\\n", b"\n")
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid or encrypted private key PEM") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Access token signing key must be an RSA private key")
    return key


class AccessTokenService:
    """Signs and verifies Access Tokens with one RSA key.

    ``clock`` must return a timezone-aware datetime; tests inject a fixed one.
    """

    def __init__(
        self,
        *,
        private_key: rsa.RSAPrivateKey,
        issuer: str,
        ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if private_key.key_size < MIN_RSA_KEY_BITS:
            raise ValueError(f"RSA key must be at least {MIN_RSA_KEY_BITS} bits")
        if not issuer:
            raise ValueError("issuer must not be empty")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be at least 1")
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._issuer = issuer
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self.key_id = _key_id(self._public_key)

    def issue(self, user_id: UUID) -> IssuedAccessToken:
        issued_at = self._clock().replace(microsecond=0)
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)
        payload = {
            "iss": self._issuer,
            "sub": str(user_id),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(
            payload, self._private_key, algorithm=ALGORITHM, headers={"kid": self.key_id}
        )
        return IssuedAccessToken(token=token, expires_in=self._ttl_seconds, expires_at=expires_at)

    def verify(self, token: str) -> AccessTokenClaims:
        """Return the claims of a valid token, or raise InvalidAccessTokenError.

        Only RS256 is accepted, whatever the token header says. The signature, expiry,
        issuer, required claims, key id and a UUID subject are all checked.
        """
        try:
            if jwt.get_unverified_header(token).get("kid") != self.key_id:
                raise InvalidAccessTokenError("Invalid access token")
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                options={"require": _REQUIRED_CLAIMS},
            )
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                issued_at=datetime.fromtimestamp(payload["iat"], UTC),
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except InvalidAccessTokenError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise InvalidAccessTokenError("Invalid access token") from exc
