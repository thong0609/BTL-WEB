import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from commerce_identity import access_tokens
from commerce_identity.access_tokens import (
    ACCESS_TOKEN_TTL_SECONDS,
    AccessTokenService,
    InvalidAccessTokenError,
)

ISSUER = "commerce-identity-test"
USER_ID = UUID("3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b")


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def service(private_key: rsa.RSAPrivateKey) -> AccessTokenService:
    return AccessTokenService(private_key=private_key, issuer=ISSUER)


def _pem(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": str(USER_ID),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _forge(
    service: AccessTokenService,
    key: rsa.RSAPrivateKey,
    *,
    payload: dict[str, Any] | None = None,
    kid: str | None = None,
) -> str:
    """Sign arbitrary claims with ``key``, labelled with the service's key id by default."""
    return jwt.encode(
        _payload() if payload is None else payload,
        key,
        algorithm="RS256",
        headers={"kid": kid or service.key_id},
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unverified_payload(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


def test_issue_then_verify_round_trip(private_key: rsa.RSAPrivateKey) -> None:
    fixed = datetime.now(UTC).replace(microsecond=0)
    fixed_service = AccessTokenService(private_key=private_key, issuer=ISSUER, clock=lambda: fixed)

    issued = fixed_service.issue(USER_ID)
    claims = fixed_service.verify(issued.token)

    assert claims.user_id == USER_ID
    assert claims.issued_at == fixed
    assert claims.expires_at == fixed + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)
    assert issued.expires_in == ACCESS_TOKEN_TTL_SECONDS == 900
    assert issued.expires_at == claims.expires_at


def test_token_header_and_payload_carry_only_the_agreed_fields(
    service: AccessTokenService,
) -> None:
    token = service.issue(uuid4()).token

    header = jwt.get_unverified_header(token)
    payload = _unverified_payload(token)

    assert header == {"alg": "RS256", "typ": "JWT", "kid": service.key_id}
    assert set(payload) == {"iss", "sub", "iat", "exp"}
    assert payload["iss"] == ISSUER
    assert payload["exp"] - payload["iat"] == 900


def test_key_id_is_stable_for_a_key_and_differs_between_keys(
    private_key: rsa.RSAPrivateKey, other_key: rsa.RSAPrivateKey
) -> None:
    first = AccessTokenService(private_key=private_key, issuer=ISSUER)
    again = AccessTokenService(private_key=private_key, issuer=ISSUER)
    other = AccessTokenService(private_key=other_key, issuer=ISSUER)

    assert first.key_id == again.key_id
    assert first.key_id != other.key_id
    assert len(first.key_id) == 43


def test_expired_token_is_rejected(private_key: rsa.RSAPrivateKey) -> None:
    past = AccessTokenService(
        private_key=private_key, issuer=ISSUER, clock=lambda: datetime(2020, 1, 1, tzinfo=UTC)
    )

    with pytest.raises(InvalidAccessTokenError):
        past.verify(past.issue(USER_ID).token)


def test_token_issued_in_the_future_is_rejected(private_key: rsa.RSAPrivateKey) -> None:
    future = AccessTokenService(
        private_key=private_key, issuer=ISSUER, clock=lambda: datetime(2100, 1, 1, tzinfo=UTC)
    )

    with pytest.raises(InvalidAccessTokenError):
        future.verify(future.issue(USER_ID).token)


def test_token_from_another_issuer_is_rejected(
    service: AccessTokenService, private_key: rsa.RSAPrivateKey
) -> None:
    foreign = AccessTokenService(private_key=private_key, issuer="someone-else")

    with pytest.raises(InvalidAccessTokenError):
        service.verify(foreign.issue(USER_ID).token)


def test_signature_from_a_different_key_is_rejected_even_with_our_key_id(
    service: AccessTokenService, other_key: rsa.RSAPrivateKey
) -> None:
    forged = _forge(service, other_key)

    with pytest.raises(InvalidAccessTokenError):
        service.verify(forged)


def test_unknown_key_id_is_rejected(
    service: AccessTokenService, private_key: rsa.RSAPrivateKey
) -> None:
    with pytest.raises(InvalidAccessTokenError):
        service.verify(_forge(service, private_key, kid="not-our-key"))


def test_missing_key_id_is_rejected(
    service: AccessTokenService, private_key: rsa.RSAPrivateKey
) -> None:
    token = jwt.encode(_payload(), private_key, algorithm="RS256")

    with pytest.raises(InvalidAccessTokenError):
        service.verify(token)


def test_alg_none_is_rejected(service: AccessTokenService) -> None:
    token = jwt.encode(_payload(), None, algorithm="none", headers={"kid": service.key_id})

    with pytest.raises(InvalidAccessTokenError):
        service.verify(token)


@pytest.mark.parametrize("encoding", [serialization.Encoding.PEM, serialization.Encoding.DER])
def test_hs256_signed_with_the_public_key_is_rejected(
    service: AccessTokenService,
    private_key: rsa.RSAPrivateKey,
    encoding: serialization.Encoding,
) -> None:
    # The classic algorithm-confusion forgery: the public key is used as an HMAC secret.
    # PyJWT refuses PEM secrets by itself; DER is only stopped by pinning RS256.
    public_bytes = private_key.public_key().public_bytes(
        encoding, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": service.key_id}).encode())
    body = _b64(json.dumps(_payload()).encode())
    signature = hmac.new(public_bytes, f"{header}.{body}".encode(), hashlib.sha256).digest()

    with pytest.raises(InvalidAccessTokenError):
        service.verify(f"{header}.{body}.{_b64(signature)}")


def test_tampered_payload_is_rejected(service: AccessTokenService) -> None:
    header, _, signature = service.issue(USER_ID).token.split(".")
    forged_body = _b64(json.dumps(_payload(sub=str(uuid4()))).encode())

    with pytest.raises(InvalidAccessTokenError):
        service.verify(f"{header}.{forged_body}.{signature}")


@pytest.mark.parametrize("missing", ["exp", "iat", "iss", "sub"])
def test_token_missing_a_required_claim_is_rejected(
    service: AccessTokenService, private_key: rsa.RSAPrivateKey, missing: str
) -> None:
    token = _forge(service, private_key, payload=_payload(**{missing: None}))

    with pytest.raises(InvalidAccessTokenError):
        service.verify(token)


@pytest.mark.parametrize("subject", ["not-a-uuid", "", "12345"])
def test_non_uuid_subject_is_rejected(
    service: AccessTokenService, private_key: rsa.RSAPrivateKey, subject: str
) -> None:
    token = _forge(service, private_key, payload=_payload(sub=subject))

    with pytest.raises(InvalidAccessTokenError):
        service.verify(token)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "....", "Bearer x.y.z"])
def test_garbage_is_rejected(service: AccessTokenService, garbage: str) -> None:
    with pytest.raises(InvalidAccessTokenError):
        service.verify(garbage)


def test_error_message_does_not_echo_the_token(service: AccessTokenService) -> None:
    token = service.issue(USER_ID).token
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    with pytest.raises(InvalidAccessTokenError) as excinfo:
        service.verify(forged)

    assert forged not in str(excinfo.value)
    assert str(excinfo.value) == "Invalid access token"


def test_weak_or_non_rsa_keys_and_bad_settings_are_rejected(
    private_key: rsa.RSAPrivateKey,
) -> None:
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)

    with pytest.raises(ValueError, match="at least 2048"):
        AccessTokenService(private_key=weak, issuer=ISSUER)
    with pytest.raises(ValueError, match="issuer"):
        AccessTokenService(private_key=private_key, issuer="")
    with pytest.raises(ValueError, match="ttl_seconds"):
        AccessTokenService(private_key=private_key, issuer=ISSUER, ttl_seconds=0)


def test_load_private_key_accepts_pem_text_bytes_and_single_line_env_form(
    private_key: rsa.RSAPrivateKey,
) -> None:
    pem = _pem(private_key)
    single_line = pem.decode().replace("\n", "\\n")
    expected = access_tokens._key_id(private_key.public_key())

    for candidate in (pem, pem.decode(), single_line):
        loaded = access_tokens.load_private_key(candidate)
        assert access_tokens._key_id(loaded.public_key()) == expected


def test_load_private_key_rejects_garbage_encrypted_and_non_rsa_keys(
    private_key: rsa.RSAPrivateKey,
) -> None:
    encrypted = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"passphrase"),
    )
    ec_pem = _pem(ec.generate_private_key(ec.SECP256R1()))

    for bad in ("", "not a pem", encrypted, ec_pem):
        with pytest.raises(ValueError):
            access_tokens.load_private_key(bad)


def test_load_private_key_error_does_not_leak_key_material(
    private_key: rsa.RSAPrivateKey,
) -> None:
    encrypted = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"passphrase"),
    )

    with pytest.raises(ValueError) as excinfo:
        access_tokens.load_private_key(encrypted)

    assert "BEGIN" not in str(excinfo.value)
