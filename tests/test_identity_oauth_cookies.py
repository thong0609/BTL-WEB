import base64
import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from commerce_identity import oauth_cookies
from commerce_identity.oauth_cookies import (
    LINK_TICKET_COOKIE_NAME,
    LINK_TICKET_TTL,
    MAX_COOKIE_VALUE_LENGTH,
    OAUTH_COOKIE_NAME,
    OAUTH_COOKIE_TTL,
    CookieCipher,
    InvalidCookieError,
    load_cookie_key,
)

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))
NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)
PAYLOAD = {
    "state": "s" * 43,
    "nonce": "n" * 43,
    "codeVerifier": "v" * 43,
    "intent": "login",
    "display": "popup",
}
URLSAFE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _seal_raw(plaintext: bytes, *, name: str = OAUTH_COOKIE_NAME, key: bytes = KEY) -> str:
    """Seal arbitrary bytes with a valid MAC, to test what happens after decryption."""
    nonce = b"\x01" * 12
    return _b64e(nonce + AESGCM(key).encrypt(nonce, plaintext, name.encode("ascii")))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def cipher(clock: Clock) -> CookieCipher:
    return CookieCipher(key=KEY, clock=clock)


def test_constants_match_the_agreed_contract() -> None:
    assert OAUTH_COOKIE_NAME == "googleOAuth"
    assert LINK_TICKET_COOKIE_NAME == "googleLinkTicket"
    assert OAUTH_COOKIE_TTL == timedelta(minutes=10)
    assert LINK_TICKET_TTL == timedelta(minutes=5)


def test_round_trip_returns_the_payload_without_exp(cipher: CookieCipher) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    assert cipher.unseal(OAUTH_COOKIE_NAME, value) == PAYLOAD


def test_round_trip_keeps_non_ascii_text(cipher: CookieCipher) -> None:
    payload = {"name": "Nguyễn Văn Á 😀"}

    value = cipher.seal(LINK_TICKET_COOKIE_NAME, payload, ttl=LINK_TICKET_TTL)

    assert cipher.unseal(LINK_TICKET_COOKIE_NAME, value) == payload


def test_value_is_cookie_safe_and_small_for_a_realistic_payload(cipher: CookieCipher) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    assert value.isascii()
    assert all(char in URLSAFE_ALPHABET for char in value)
    assert len(value) < 1000


def test_plaintext_is_not_visible_in_the_value(cipher: CookieCipher) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)
    raw = _b64d(value)

    assert b"codeVerifier" not in raw
    assert b"vvvvvvvv" not in raw
    assert b"popup" not in raw


def test_every_seal_uses_a_fresh_nonce(cipher: CookieCipher) -> None:
    first = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)
    second = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    assert first != second
    assert _b64d(first)[:12] != _b64d(second)[:12]


def test_nonce_is_twelve_random_bytes_from_os_urandom(
    cipher: CookieCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[int] = []

    def fake_urandom(size: int) -> bytes:
        requested.append(size)
        return b"\x07" * size

    monkeypatch.setattr(oauth_cookies.os, "urandom", fake_urandom)

    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    assert requested == [12]
    assert _b64d(value)[:12] == b"\x07" * 12


@pytest.mark.parametrize(
    ("sealed_for", "opened_as"),
    [
        (OAUTH_COOKIE_NAME, LINK_TICKET_COOKIE_NAME),
        (LINK_TICKET_COOKIE_NAME, OAUTH_COOKIE_NAME),
    ],
)
def test_value_sealed_for_one_cookie_is_rejected_under_another_name(
    cipher: CookieCipher, sealed_for: str, opened_as: str
) -> None:
    value = cipher.seal(sealed_for, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    with pytest.raises(InvalidCookieError):
        cipher.unseal(opened_as, value)


def test_value_sealed_with_another_key_is_rejected(clock: Clock) -> None:
    value = CookieCipher(key=OTHER_KEY, clock=clock).seal(
        OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL
    )

    with pytest.raises(InvalidCookieError):
        CookieCipher(key=KEY, clock=clock).unseal(OAUTH_COOKIE_NAME, value)


@pytest.mark.parametrize(("elapsed", "valid"), [(0, True), (599, True), (600, False), (601, False)])
def test_cookie_expires_exactly_at_exp(
    cipher: CookieCipher, clock: Clock, elapsed: int, valid: bool
) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)
    clock.now = NOW + timedelta(seconds=elapsed)

    if valid:
        assert cipher.unseal(OAUTH_COOKIE_NAME, value) == PAYLOAD
    else:
        with pytest.raises(InvalidCookieError):
            cipher.unseal(OAUTH_COOKIE_NAME, value)


def test_link_ticket_ttl_is_five_minutes(cipher: CookieCipher, clock: Clock) -> None:
    value = cipher.seal(LINK_TICKET_COOKIE_NAME, PAYLOAD, ttl=LINK_TICKET_TTL)

    clock.now = NOW + timedelta(seconds=299)
    assert cipher.unseal(LINK_TICKET_COOKIE_NAME, value) == PAYLOAD
    clock.now = NOW + timedelta(seconds=300)
    with pytest.raises(InvalidCookieError):
        cipher.unseal(LINK_TICKET_COOKIE_NAME, value)


def test_ttl_of_one_second_is_the_minimum(cipher: CookieCipher, clock: Clock) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=timedelta(seconds=1))

    assert cipher.unseal(OAUTH_COOKIE_NAME, value) == PAYLOAD
    clock.now = NOW + timedelta(seconds=1)
    with pytest.raises(InvalidCookieError):
        cipher.unseal(OAUTH_COOKIE_NAME, value)


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(milliseconds=999), timedelta(seconds=-5)])
def test_ttl_below_one_second_is_rejected(cipher: CookieCipher, ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="ttl"):
        cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=ttl)


def test_exp_is_reserved(cipher: CookieCipher) -> None:
    with pytest.raises(ValueError, match="exp"):
        cipher.seal(OAUTH_COOKIE_NAME, {"exp": 1}, ttl=OAUTH_COOKIE_TTL)


@pytest.mark.parametrize("index", [0, 11, 12, 20, -1])
def test_flipping_any_byte_is_rejected(cipher: CookieCipher, index: int) -> None:
    raw = bytearray(_b64d(cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)))
    raw[index] ^= 0x01

    with pytest.raises(InvalidCookieError):
        cipher.unseal(OAUTH_COOKIE_NAME, _b64e(bytes(raw)))


def test_truncated_value_is_rejected(cipher: CookieCipher) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    with pytest.raises(InvalidCookieError):
        cipher.unseal(OAUTH_COOKIE_NAME, value[:-4])


@pytest.mark.parametrize(
    "garbage",
    ["", "A", "AAAA", "A" * 20, "!!!!", "has space", "a+b/c", "tab\there", "é" * 30],
)
def test_garbage_is_rejected(cipher: CookieCipher, garbage: str) -> None:
    with pytest.raises(InvalidCookieError):
        cipher.unseal(OAUTH_COOKIE_NAME, garbage)


def test_trailing_newline_or_padding_is_rejected(cipher: CookieCipher) -> None:
    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    for variant in (value + "\n", value + "=", value + "A"):
        with pytest.raises(InvalidCookieError):
            cipher.unseal(OAUTH_COOKIE_NAME, variant)


def test_non_canonical_encoding_of_a_valid_value_is_rejected(cipher: CookieCipher) -> None:
    for pad in range(3):
        value = cipher.seal(OAUTH_COOKIE_NAME, {"pad": "x" * pad}, ttl=OAUTH_COOKIE_TTL)
        if len(_b64d(value)) % 3:
            break
    else:  # pragma: no cover
        pytest.fail("could not build a value whose last character has spare bits")
    twisted = value[:-1] + URLSAFE_ALPHABET[URLSAFE_ALPHABET.index(value[-1]) ^ 1]
    assert _b64d(twisted) == _b64d(value)

    with pytest.raises(InvalidCookieError):
        cipher.unseal(OAUTH_COOKIE_NAME, twisted)


def test_authenticated_value_with_a_valid_body_is_accepted() -> None:
    cipher = CookieCipher(key=KEY, clock=lambda: NOW)
    exp = int(NOW.timestamp()) + 60

    assert cipher.unseal(OAUTH_COOKIE_NAME, _seal_raw(b'{"a":1,"exp":%d}' % exp)) == {"a": 1}


@pytest.mark.parametrize(
    "plaintext",
    [
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'"text"',
        b"null",
        b"42",
        b'{"a":1}',
        b'{"a":1,"exp":null}',
        b'{"a":1,"exp":"9999999999"}',
        b'{"a":1,"exp":true}',
        b'{"a":1,"exp":99999999999.0}',
        b'{"a":1,"exp":[9999999999]}',
    ],
)
def test_authenticated_value_with_a_bad_body_is_rejected(plaintext: bytes) -> None:
    cipher = CookieCipher(key=KEY, clock=lambda: NOW)

    with pytest.raises(InvalidCookieError):
        cipher.unseal(OAUTH_COOKIE_NAME, _seal_raw(plaintext))


def test_error_message_is_generic_and_does_not_echo_the_value(cipher: CookieCipher) -> None:
    value = "this-looks-like-a-secret-cookie-value"

    with pytest.raises(InvalidCookieError) as excinfo:
        cipher.unseal(OAUTH_COOKIE_NAME, value)

    assert str(excinfo.value) == "Invalid cookie"
    assert value not in repr(excinfo.value)


def test_original_error_is_kept_as_the_cause(cipher: CookieCipher) -> None:
    raw = bytearray(_b64d(cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)))
    raw[-1] ^= 0x01

    with pytest.raises(InvalidCookieError) as excinfo:
        cipher.unseal(OAUTH_COOKIE_NAME, _b64e(bytes(raw)))

    assert isinstance(excinfo.value.__cause__, InvalidTag)


def test_value_at_the_size_limit_is_accepted_and_one_more_group_is_rejected(
    cipher: CookieCipher,
) -> None:
    base = len(json.dumps({"k": "", "exp": int(NOW.timestamp()) + 600}, separators=(",", ":")))
    # 28 bytes of nonce+tag plus the JSON make 3000 bytes, i.e. exactly 4000 characters.
    padding = 3000 - 28 - base

    value = cipher.seal(OAUTH_COOKIE_NAME, {"k": "x" * padding}, ttl=OAUTH_COOKIE_TTL)
    assert len(value) == MAX_COOKIE_VALUE_LENGTH == 4000
    assert cipher.unseal(OAUTH_COOKIE_NAME, value) == {"k": "x" * padding}

    with pytest.raises(ValueError, match="too large"):
        cipher.seal(OAUTH_COOKIE_NAME, {"k": "x" * (padding + 1)}, ttl=OAUTH_COOKIE_TTL)


@pytest.mark.parametrize("name", ["", "tên"])
def test_bad_cookie_names_are_rejected(cipher: CookieCipher, name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        cipher.seal(name, PAYLOAD, ttl=OAUTH_COOKIE_TTL)
    with pytest.raises(ValueError, match="name"):
        cipher.unseal(name, "AAAA")


def test_naive_clock_is_rejected() -> None:
    cipher = CookieCipher(key=KEY, clock=lambda: datetime(2026, 11, 26, 12, 0, 0))

    with pytest.raises(ValueError, match="timezone-aware"):
        cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)


def test_default_clock_is_the_real_utc_time() -> None:
    cipher = CookieCipher(key=KEY)

    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    assert cipher.unseal(OAUTH_COOKIE_NAME, value) == PAYLOAD


@pytest.mark.parametrize("size", [0, 16, 24, 31, 33])
def test_cipher_requires_a_32_byte_key(size: int) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        CookieCipher(key=b"k" * size)


def test_load_cookie_key_decodes_base64url_of_32_bytes() -> None:
    secret = secrets.token_urlsafe(32)

    key = load_cookie_key(secret)

    assert len(key) == 32
    assert _b64e(key) == secret


def test_load_cookie_key_accepts_one_trailing_padding_character() -> None:
    secret = secrets.token_urlsafe(32)

    assert load_cookie_key(secret + "=") == load_cookie_key(secret)


def test_load_cookie_key_result_works_with_the_cipher(clock: Clock) -> None:
    cipher = CookieCipher(key=load_cookie_key(secrets.token_urlsafe(32)), clock=clock)

    value = cipher.seal(OAUTH_COOKIE_NAME, PAYLOAD, ttl=OAUTH_COOKIE_TTL)

    assert cipher.unseal(OAUTH_COOKIE_NAME, value) == PAYLOAD


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "A" * 42,
        "A" * 44,
        "A" * 43 + "==",
        "+" + "A" * 42,
        "/" + "A" * 42,
        " " + "A" * 42,
        "A" * 42 + "\n",
        "0123456789abcdef" * 4,
        "A" * 42 + "B",
        "é" + "A" * 42,
    ],
)
def test_load_cookie_key_rejects_anything_else(bad: str) -> None:
    with pytest.raises(ValueError, match="OAUTH_COOKIE_SECRET") as excinfo:
        load_cookie_key(bad)

    if bad.strip():
        assert bad not in str(excinfo.value)


def test_load_cookie_key_accepts_the_all_zero_key() -> None:
    assert load_cookie_key("A" * 43) == bytes(32)
