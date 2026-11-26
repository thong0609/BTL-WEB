"""Verification of Google ID Tokens (IDN-02, IDN-12).

Google only proves who the person is; Identity issues its own tokens. This module takes
the ID Token returned by Google's token endpoint and checks it with PyJWT against
Google's published signing keys (JWKS), downloaded with httpx:

* RS256 only, whatever the token header says;
* ``iss`` is ``https://accounts.google.com`` or ``accounts.google.com``;
* ``aud`` is our OAuth client id; ``exp``, ``iat``, ``sub`` must be present and valid;
* ``nonce`` equals the value the login started with;
* the email is present and ``email_verified`` is exactly ``true``.

Keys are cached in the process. An unknown ``kid`` triggers a reload, but reloads are
rate-limited so a stream of tokens with random key ids cannot make Identity hammer
Google. If a reload fails, a key that is already cached is still used.

``GoogleIdentity.email`` is returned as Google sent it: trimming and lowercasing belong to
the single email normalisation used for ``users.email``.
"""

import asyncio
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

# Value of jwks_uri in https://accounts.google.com/.well-known/openid-configuration.
GOOGLE_JWKS_URL: Final = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS: Final = ("https://accounts.google.com", "accounts.google.com")
ALGORITHM: Final = "RS256"
LEEWAY_SECONDS: Final = 30
KEYS_MAX_AGE_SECONDS: Final = 3600.0
KEYS_MIN_REFRESH_INTERVAL_SECONDS: Final = 60.0
JWKS_TIMEOUT_SECONDS: Final = 5.0
MIN_KEY_BITS: Final = 2048
MAX_SUBJECT_LENGTH: Final = 255  # user_identities.provider_subject is varchar(255)
MAX_EMAIL_LENGTH: Final = 254  # users.email is varchar(254)
_REQUIRED_CLAIMS: Final = ["aud", "exp", "iat", "iss", "sub"]


class GoogleIdTokenError(Exception):
    """The ID Token is not acceptable. The message is generic on purpose."""


class GoogleEmailUnverifiedError(GoogleIdTokenError):
    """The token is genuine but carries no verified email (GOOGLE_EMAIL_UNVERIFIED)."""


class GoogleKeysUnavailableError(Exception):
    """Google's signing keys could not be loaded: a dependency failure, not a bad token."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str | None


def _parse_jwks(document: Any) -> dict[str, rsa.RSAPublicKey]:
    entries = document.get("keys") if isinstance(document, dict) else None
    keys: dict[str, rsa.RSAPublicKey] = {}
    if not isinstance(entries, list):
        return keys
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid:
            continue
        if entry.get("kty") != "RSA" or entry.get("alg", ALGORITHM) != ALGORITHM:
            continue
        if entry.get("use", "sig") != "sig":
            continue
        try:
            key = RSAAlgorithm.from_jwk(json.dumps(entry))
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            continue
        if isinstance(key, rsa.RSAPublicKey) and key.key_size >= MIN_KEY_BITS:
            keys[kid] = key
    return keys


class GoogleIdTokenVerifier:
    """Verifies Google ID Tokens for one OAuth client.

    ``http_client`` is owned by the caller (created once at startup, closed at shutdown)
    and should not follow redirects. ``clock`` returns monotonic seconds; tests inject one.
    """

    def __init__(
        self,
        *,
        client_id: str,
        http_client: httpx.AsyncClient,
        jwks_url: str = GOOGLE_JWKS_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not client_id:
            raise ValueError("client_id must not be empty")
        self._client_id = client_id
        self._http = http_client
        self._jwks_url = jwks_url
        self._clock = clock
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._fetched_at: float | None = None
        self._last_attempt_at: float | None = None
        self._lock = asyncio.Lock()

    async def verify(self, id_token: str, *, expected_nonce: str) -> GoogleIdentity:
        """Return the verified identity, or raise.

        GoogleEmailUnverifiedError (a GoogleIdTokenError) when the token is genuine but
        has no verified email; GoogleIdTokenError for any other bad token;
        GoogleKeysUnavailableError when Google's keys cannot be loaded.
        """
        if not expected_nonce:
            raise ValueError("expected_nonce must not be empty")
        try:
            header = jwt.get_unverified_header(id_token)
            kid = header.get("kid")
            if header.get("alg") != ALGORITHM or not isinstance(kid, str) or not kid:
                raise GoogleIdTokenError("Invalid Google ID token")
            key = await self._key_for(kid)
            payload = jwt.decode(
                id_token,
                key,
                algorithms=[ALGORITHM],
                audience=self._client_id,
                issuer=list(GOOGLE_ISSUERS),
                leeway=LEEWAY_SECONDS,
                options={"require": _REQUIRED_CLAIMS},
            )
            return self._identity_from(payload, expected_nonce)
        except (GoogleIdTokenError, GoogleKeysUnavailableError):
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise GoogleIdTokenError("Invalid Google ID token") from exc

    @staticmethod
    def _identity_from(payload: dict[str, Any], expected_nonce: str) -> GoogleIdentity:
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(
            nonce.encode("utf-8"), expected_nonce.encode("utf-8")
        ):
            raise GoogleIdTokenError("Invalid Google ID token")
        subject = payload["sub"]
        if not isinstance(subject, str) or not 0 < len(subject) <= MAX_SUBJECT_LENGTH:
            raise GoogleIdTokenError("Invalid Google ID token")
        email = payload.get("email")
        if not isinstance(email, str) or not email or payload.get("email_verified") is not True:
            raise GoogleEmailUnverifiedError("Google account has no verified email")
        if len(email) > MAX_EMAIL_LENGTH:
            raise GoogleIdTokenError("Invalid Google ID token")
        raw_name = payload.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
        return GoogleIdentity(subject=subject, email=email, name=name)

    def _age(self) -> float | None:
        return None if self._fetched_at is None else self._clock() - self._fetched_at

    def _cached_key(self, kid: str) -> rsa.RSAPublicKey | None:
        age = self._age()
        if age is None or age >= KEYS_MAX_AGE_SECONDS:
            return None
        return self._keys.get(kid)

    def _may_refresh(self) -> bool:
        if self._last_attempt_at is None:
            return True
        return self._clock() - self._last_attempt_at >= KEYS_MIN_REFRESH_INTERVAL_SECONDS

    async def _key_for(self, kid: str) -> rsa.RSAPublicKey:
        key = self._cached_key(kid)
        if key is not None:
            return key
        async with self._lock:
            # Tasks that waited here find the keys just loaded: the reload interval keeps
            # them from downloading again.
            if self._may_refresh():
                try:
                    await self._refresh()
                except GoogleKeysUnavailableError:
                    stale = self._keys.get(kid)
                    if stale is None:
                        raise
                    return stale
            elif self._fetched_at is None:
                raise GoogleKeysUnavailableError("Google signing keys are not available")
            key = self._keys.get(kid)
            if key is None:
                raise GoogleIdTokenError("Invalid Google ID token")
            return key

    async def _refresh(self) -> None:
        self._last_attempt_at = self._clock()
        try:
            response = await self._http.get(self._jwks_url, timeout=JWKS_TIMEOUT_SECONDS)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleKeysUnavailableError("Could not load Google signing keys") from exc
        keys = _parse_jwks(document)
        if not keys:
            raise GoogleKeysUnavailableError("Google signing keys response had no usable key")
        self._keys = keys
        self._fetched_at = self._clock()
