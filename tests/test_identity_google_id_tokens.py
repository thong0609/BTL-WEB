import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from commerce_identity.google_id_tokens import (
    GOOGLE_JWKS_URL,
    GoogleEmailUnverifiedError,
    GoogleIdentity,
    GoogleIdTokenError,
    GoogleIdTokenVerifier,
    GoogleKeysUnavailableError,
)

CLIENT_ID = "test-client.apps.googleusercontent.com"
KID = "test-key-1"
NONCE = "n-0S6_WzA2Mj"
SUBJECT = "109876543210987654321"
EMAIL = "student@gmail.com"


@pytest.fixture(scope="module")
def key_a() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def key_b() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class JwksServer:
    """Stands in for Google's JWKS endpoint and records every request."""

    def __init__(self, keys: dict[str, rsa.RSAPrivateKey]) -> None:
        self.keys = keys
        self.requests: list[httpx.Request] = []
        self.failure: str | None = None
        self.extra_entries: list[Any] = []
        self.delay = 0.0

    def _document(self) -> dict[str, Any]:
        entries = [_jwk(key, kid) for kid, key in self.keys.items()] + self.extra_entries
        return {"keys": entries}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # Yield to the event loop like a real network call would.
        await asyncio.sleep(self.delay)
        if self.failure == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        # Error statuses still carry a perfectly valid key set: only the status can reject them.
        if self.failure == "status":
            return httpx.Response(503, json=self._document())
        if self.failure == "redirect":
            return httpx.Response(
                302, json=self._document(), headers={"location": "https://evil.example/certs"}
            )
        if self.failure == "json":
            return httpx.Response(200, content=b"<html>not json</html>")
        if self.failure == "empty":
            return httpx.Response(200, json={"keys": []})
        if self.failure == "shape":
            return httpx.Response(200, json=["keys"])
        return httpx.Response(200, json=self._document())


def _token(
    key: rsa.RSAPrivateKey,
    *,
    kid: str | None = KID,
    alg: str = "RS256",
    **overrides: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": SUBJECT,
        "email": EMAIL,
        "email_verified": True,
        "name": "Nguyen Van A",
        "nonce": NONCE,
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(overrides)
    payload = {name: value for name, value in payload.items() if value is not None}
    headers = {} if kid is None else {"kid": kid}
    return jwt.encode(payload, key, algorithm=alg, headers=headers)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _run[T](
    server: JwksServer,
    scenario: Callable[[GoogleIdTokenVerifier], Awaitable[T]],
    clock: FakeClock | None = None,
) -> T:
    async def main() -> T:
        transport = httpx.MockTransport(server.handler)
        async with httpx.AsyncClient(transport=transport) as client:
            verifier = GoogleIdTokenVerifier(
                client_id=CLIENT_ID, http_client=client, clock=clock or FakeClock()
            )
            return await scenario(verifier)

    return asyncio.run(main())


def _verify(
    server: JwksServer, token: str, *, nonce: str = NONCE, clock: FakeClock | None = None
) -> GoogleIdentity:
    return _run(server, lambda verifier: verifier.verify(token, expected_nonce=nonce), clock)


def test_valid_token_returns_the_identity_and_fetches_keys_once(
    key_a: rsa.RSAPrivateKey,
) -> None:
    server = JwksServer({KID: key_a})

    identity = _verify(server, _token(key_a))

    assert identity == GoogleIdentity(subject=SUBJECT, email=EMAIL, name="Nguyen Van A")
    assert len(server.requests) == 1
    assert server.requests[0].method == "GET"
    assert GOOGLE_JWKS_URL == "https://www.googleapis.com/oauth2/v3/certs"
    assert str(server.requests[0].url) == GOOGLE_JWKS_URL


def test_email_is_returned_exactly_as_google_sent_it(key_a: rsa.RSAPrivateKey) -> None:
    server = JwksServer({KID: key_a})

    identity = _verify(server, _token(key_a, email="Student.Name@Gmail.com"))

    assert identity.email == "Student.Name@Gmail.com"


@pytest.mark.parametrize("issuer", ["https://accounts.google.com", "accounts.google.com"])
def test_both_google_issuer_forms_are_accepted(key_a: rsa.RSAPrivateKey, issuer: str) -> None:
    assert _verify(JwksServer({KID: key_a}), _token(key_a, iss=issuer)).subject == SUBJECT


@pytest.mark.parametrize(
    "issuer",
    [
        "https://evil.example",
        "accounts.google.com.evil.example",
        "http://accounts.google.com",
        "https://accounts.google.com/",
        "ACCOUNTS.GOOGLE.COM",
        "",
    ],
)
def test_other_issuers_are_rejected(key_a: rsa.RSAPrivateKey, issuer: str) -> None:
    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_a, iss=issuer))


@pytest.mark.parametrize(
    "audience", ["another-client.apps.googleusercontent.com", "", ["x", "y"], CLIENT_ID.upper()]
)
def test_other_audiences_are_rejected(key_a: rsa.RSAPrivateKey, audience: Any) -> None:
    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_a, aud=audience))


@pytest.mark.parametrize("missing", ["aud", "exp", "iat", "iss", "sub"])
def test_missing_required_claims_are_rejected(key_a: rsa.RSAPrivateKey, missing: str) -> None:
    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_a, **{missing: None}))


def test_expired_token_is_rejected(key_a: rsa.RSAPrivateKey) -> None:
    long_ago = int(time.time()) - 7200

    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_a, iat=long_ago - 3600, exp=long_ago))


def test_token_issued_far_in_the_future_is_rejected_but_small_skew_is_tolerated(
    key_a: rsa.RSAPrivateKey,
) -> None:
    now = int(time.time())

    assert _verify(JwksServer({KID: key_a}), _token(key_a, iat=now + 10)).subject == SUBJECT
    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_a, iat=now + 300, exp=now + 3900))


@pytest.mark.parametrize("nonce", ["wrong-nonce", NONCE.upper(), NONCE + " ", "", None, 12345])
def test_wrong_missing_or_non_string_nonce_is_rejected(
    key_a: rsa.RSAPrivateKey, nonce: Any
) -> None:
    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_a, nonce=nonce))


def test_empty_expected_nonce_is_a_programming_error(key_a: rsa.RSAPrivateKey) -> None:
    server = JwksServer({KID: key_a})

    with pytest.raises(ValueError, match="expected_nonce"):
        _verify(server, _token(key_a), nonce="")
    assert server.requests == []


def test_alg_none_is_rejected_without_contacting_google(key_a: rsa.RSAPrivateKey) -> None:
    server = JwksServer({KID: key_a})
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": SUBJECT,
        "email": EMAIL,
        "email_verified": True,
        "nonce": NONCE,
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(payload, None, algorithm="none", headers={"kid": KID})

    with pytest.raises(GoogleIdTokenError):
        _verify(server, token)
    assert server.requests == []


def test_other_rsa_algorithms_are_rejected_even_with_a_valid_key(
    key_a: rsa.RSAPrivateKey,
) -> None:
    server = JwksServer({KID: key_a})

    with pytest.raises(GoogleIdTokenError):
        _verify(server, _token(key_a, alg="RS384"))
    assert server.requests == []


@pytest.mark.parametrize("encoding", [serialization.Encoding.PEM, serialization.Encoding.DER])
def test_hs256_signed_with_the_public_key_is_rejected(
    key_a: rsa.RSAPrivateKey, encoding: serialization.Encoding
) -> None:
    server = JwksServer({KID: key_a})
    public_bytes = key_a.public_key().public_bytes(
        encoding, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    body = _b64(
        json.dumps(
            {
                "iss": "https://accounts.google.com",
                "aud": CLIENT_ID,
                "sub": SUBJECT,
                "email": EMAIL,
                "email_verified": True,
                "nonce": NONCE,
                "iat": now,
                "exp": now + 3600,
            }
        ).encode()
    )
    signature = hmac.new(public_bytes, f"{header}.{body}".encode(), hashlib.sha256).digest()

    with pytest.raises(GoogleIdTokenError):
        _verify(server, f"{header}.{body}.{_b64(signature)}")
    assert server.requests == []


def test_signature_from_another_key_is_rejected_even_with_a_known_kid(
    key_a: rsa.RSAPrivateKey, key_b: rsa.RSAPrivateKey
) -> None:
    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), _token(key_b))


def test_tampered_payload_is_rejected(key_a: rsa.RSAPrivateKey) -> None:
    header, _, signature = _token(key_a).split(".")
    forged = _b64(json.dumps({"sub": "attacker", "email": EMAIL}).encode())

    with pytest.raises(GoogleIdTokenError):
        _verify(JwksServer({KID: key_a}), f"{header}.{forged}.{signature}")


def test_missing_kid_is_rejected_without_contacting_google(key_a: rsa.RSAPrivateKey) -> None:
    server = JwksServer({KID: key_a})

    with pytest.raises(GoogleIdTokenError):
        _verify(server, _token(key_a, kid=None))
    assert server.requests == []


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "....", "Bearer x.y.z"])
def test_garbage_is_rejected_without_contacting_google(garbage: str) -> None:
    server = JwksServer({})

    with pytest.raises(GoogleIdTokenError) as excinfo:
        _verify(server, garbage)

    assert str(excinfo.value) == "Invalid Google ID token"
    assert server.requests == []


def test_error_message_does_not_echo_the_token(key_a: rsa.RSAPrivateKey) -> None:
    token = _token(key_a, aud="someone-else")

    with pytest.raises(GoogleIdTokenError) as excinfo:
        _verify(JwksServer({KID: key_a}), token)

    assert token not in str(excinfo.value)
    assert str(excinfo.value) == "Invalid Google ID token"


def test_unknown_kid_is_rejected_and_reloads_are_rate_limited(
    key_a: rsa.RSAPrivateKey, key_b: rsa.RSAPrivateKey
) -> None:
    server = JwksServer({KID: key_a})
    clock = FakeClock()
    stranger = _token(key_b, kid="never-published")

    async def scenario(verifier: GoogleIdTokenVerifier) -> None:
        # Advances add up: 0 + 5 + 20 + 30 = 55 seconds, still inside the 60 s interval.
        for advance in (0, 5, 20, 30):
            clock.advance(advance)
            with pytest.raises(GoogleIdTokenError):
                await verifier.verify(stranger, expected_nonce=NONCE)
        assert len(server.requests) == 1
        clock.advance(61)
        with pytest.raises(GoogleIdTokenError):
            await verifier.verify(stranger, expected_nonce=NONCE)
        assert len(server.requests) == 2

    _run(server, scenario, clock)


def test_key_rotation_is_picked_up_after_the_reload_interval(
    key_a: rsa.RSAPrivateKey, key_b: rsa.RSAPrivateKey
) -> None:
    server = JwksServer({KID: key_a})
    clock = FakeClock()

    async def scenario(verifier: GoogleIdTokenVerifier) -> None:
        await verifier.verify(_token(key_a), expected_nonce=NONCE)
        assert len(server.requests) == 1
        server.keys = {KID: key_a, "test-key-2": key_b}
        new_token = _token(key_b, kid="test-key-2")
        clock.advance(10)
        with pytest.raises(GoogleIdTokenError):
            await verifier.verify(new_token, expected_nonce=NONCE)
        assert len(server.requests) == 1
        clock.advance(60)
        identity = await verifier.verify(new_token, expected_nonce=NONCE)
        assert identity.subject == SUBJECT
        assert len(server.requests) == 2

    _run(server, scenario, clock)


def test_keys_are_cached_and_reloaded_after_the_max_age(key_a: rsa.RSAPrivateKey) -> None:
    server = JwksServer({KID: key_a})
    clock = FakeClock()

    async def scenario(verifier: GoogleIdTokenVerifier) -> None:
        for _ in range(3):
            await verifier.verify(_token(key_a), expected_nonce=NONCE)
            clock.advance(100)
        assert len(server.requests) == 1
        clock.advance(3600)
        await verifier.verify(_token(key_a), expected_nonce=NONCE)
        assert len(server.requests) == 2

    _run(server, scenario, clock)


def test_concurrent_verifications_share_one_download(key_a: rsa.RSAPrivateKey) -> None:
    server = JwksServer({KID: key_a})
    server.delay = 0.05

    async def scenario(verifier: GoogleIdTokenVerifier) -> list[GoogleIdentity]:
        token = _token(key_a)
        return list(
            await asyncio.gather(*(verifier.verify(token, expected_nonce=NONCE) for _ in range(5)))
        )

    identities = _run(server, scenario)

    assert len(identities) == 5
    assert len(server.requests) == 1


@pytest.mark.parametrize("failure", ["connect", "status", "redirect", "json", "empty", "shape"])
def test_unreachable_or_unusable_keys_are_a_dependency_failure_not_a_bad_token(
    key_a: rsa.RSAPrivateKey, failure: str
) -> None:
    server = JwksServer({KID: key_a})
    server.failure = failure

    with pytest.raises(GoogleKeysUnavailableError) as excinfo:
        _verify(server, _token(key_a))

    assert not isinstance(excinfo.value, GoogleIdTokenError)
    assert len(server.requests) == 1


def test_failed_downloads_are_retried_only_after_the_reload_interval(
    key_a: rsa.RSAPrivateKey,
) -> None:
    server = JwksServer({KID: key_a})
    server.failure = "connect"
    clock = FakeClock()

    async def scenario(verifier: GoogleIdTokenVerifier) -> None:
        for _ in range(3):
            with pytest.raises(GoogleKeysUnavailableError):
                await verifier.verify(_token(key_a), expected_nonce=NONCE)
        assert len(server.requests) == 1
        clock.advance(61)
        server.failure = None
        identity = await verifier.verify(_token(key_a), expected_nonce=NONCE)
        assert identity.subject == SUBJECT
        assert len(server.requests) == 2

    _run(server, scenario, clock)


def test_a_cached_key_keeps_working_when_a_reload_fails(
    key_a: rsa.RSAPrivateKey, key_b: rsa.RSAPrivateKey
) -> None:
    server = JwksServer({KID: key_a})
    clock = FakeClock()

    async def scenario(verifier: GoogleIdTokenVerifier) -> None:
        await verifier.verify(_token(key_a), expected_nonce=NONCE)
        clock.advance(3601)
        server.failure = "connect"
        identity = await verifier.verify(_token(key_a), expected_nonce=NONCE)
        assert identity.subject == SUBJECT
        assert len(server.requests) == 2
        clock.advance(61)
        with pytest.raises(GoogleKeysUnavailableError):
            await verifier.verify(_token(key_b, kid="other"), expected_nonce=NONCE)

    _run(server, scenario, clock)


@pytest.mark.filterwarnings("ignore:The RSA key is 1024 bits long:UserWarning")
def test_unusable_jwks_entries_are_ignored(
    key_a: rsa.RSAPrivateKey, key_b: rsa.RSAPrivateKey
) -> None:
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    server = JwksServer({KID: key_a})
    server.extra_entries = [
        "garbage",
        {"kty": "EC", "kid": "ec", "crv": "P-256", "x": "AA", "y": "AA"},
        {"kty": "RSA", "n": "AQAB", "e": "AQAB"},
        {"kty": "RSA", "kid": "broken", "n": "!!!", "e": "AQAB"},
        {**_jwk(key_b, "private"), "d": "AQAB"},
        {**RSAAlgorithm.to_jwk(key_b, as_dict=True), "kid": "full-private", "use": "sig"},
        {**_jwk(key_b, "encryption"), "use": "enc"},
        {**_jwk(key_b, "other-alg"), "alg": "RS384"},
        _jwk(weak, "weak"),
    ]

    async def scenario(verifier: GoogleIdTokenVerifier) -> None:
        identity = await verifier.verify(_token(key_a), expected_nonce=NONCE)
        assert identity.subject == SUBJECT
        for kid, key in [
            ("private", key_b),
            ("full-private", key_b),
            ("encryption", key_b),
            ("other-alg", key_b),
            ("weak", weak),
            ("broken", key_b),
        ]:
            with pytest.raises(GoogleIdTokenError):
                await verifier.verify(_token(key, kid=kid), expected_nonce=NONCE)

    _run(server, scenario)


@pytest.mark.parametrize(
    "claims",
    [
        {"email_verified": False},
        {"email_verified": None},
        {"email_verified": "true"},
        {"email_verified": 1},
        {"email": None},
        {"email": ""},
        {"email": 42},
    ],
)
def test_email_must_be_present_and_verified(
    key_a: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    with pytest.raises(GoogleEmailUnverifiedError) as excinfo:
        _verify(JwksServer({KID: key_a}), _token(key_a, **claims))

    assert isinstance(excinfo.value, GoogleIdTokenError)


def test_unverified_email_is_only_reported_for_a_genuine_token(
    key_a: rsa.RSAPrivateKey, key_b: rsa.RSAPrivateKey
) -> None:
    with pytest.raises(GoogleIdTokenError) as excinfo:
        _verify(JwksServer({KID: key_a}), _token(key_b, email_verified=False))

    assert not isinstance(excinfo.value, GoogleEmailUnverifiedError)


def test_email_length_is_limited_to_the_users_column(key_a: rsa.RSAPrivateKey) -> None:
    longest = "a" * 244 + "@gmail.com"
    too_long = "a" * 245 + "@gmail.com"
    assert len(longest) == 254

    assert _verify(JwksServer({KID: key_a}), _token(key_a, email=longest)).email == longest
    with pytest.raises(GoogleIdTokenError) as excinfo:
        _verify(JwksServer({KID: key_a}), _token(key_a, email=too_long))
    assert not isinstance(excinfo.value, GoogleEmailUnverifiedError)


def test_subject_length_is_limited_to_the_identity_column(key_a: rsa.RSAPrivateKey) -> None:
    longest = "1" * 255

    assert _verify(JwksServer({KID: key_a}), _token(key_a, sub=longest)).subject == longest
    for bad in ("", "1" * 256, 12345):
        with pytest.raises(GoogleIdTokenError):
            _verify(JwksServer({KID: key_a}), _token(key_a, sub=bad))


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("  Nguyễn Văn A  ", "Nguyễn Văn A"),
        ("   ", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_name_is_trimmed_and_optional(
    key_a: rsa.RSAPrivateKey, claim: Any, expected: str | None
) -> None:
    assert _verify(JwksServer({KID: key_a}), _token(key_a, name=claim)).name == expected


def test_client_id_is_required() -> None:
    async def main() -> None:
        async with httpx.AsyncClient() as client:
            GoogleIdTokenVerifier(client_id="", http_client=client)

    with pytest.raises(ValueError, match="client_id"):
        asyncio.run(main())
