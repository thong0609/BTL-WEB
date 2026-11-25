import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from commerce_identity import refresh_tokens
from commerce_identity.refresh_tokens import (
    ABSOLUTE_TTL,
    IDLE_TTL,
    MalformedRefreshTokenError,
    family_expires_at,
    generate_refresh_token,
    hash_refresh_token,
    idle_expires_at,
    new_refresh_token,
)

# Same pattern as ck_refresh_sessions_token_hash_format in the Identity schema.
TOKEN_HASH_FORMAT = re.compile(r"[0-9a-f]{64}")
NOW = datetime(2026, 11, 24, 9, 30, tzinfo=UTC)


def test_generated_tokens_are_43_url_safe_characters_and_unique() -> None:
    tokens = {generate_refresh_token() for _ in range(2000)}

    assert len(tokens) == 2000
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", token) for token in tokens)


def test_token_is_made_from_32_random_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[int] = []

    def fake_token_urlsafe(nbytes: int) -> str:
        requested.append(nbytes)
        return "B" * 43

    monkeypatch.setattr(refresh_tokens.secrets, "token_urlsafe", fake_token_urlsafe)

    assert generate_refresh_token() == "B" * 43
    assert requested == [32]
    assert refresh_tokens.REFRESH_TOKEN_BYTES == 32


def test_hash_matches_known_sha256_vectors() -> None:
    assert hash_refresh_token("A" * 43) == (
        "0f007385b6f9d4b7eeb2748605afe1a984a0a3bfa3f014d09e2a784ce9e5cd1a"
    )
    assert hash_refresh_token("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLM-_09") == (
        "d5222b97db4d186dac825a4d8be66fb66e7c9857eb4b7129e5362b6de6139653"
    )


def test_hash_is_deterministic_and_fits_the_database_check() -> None:
    token = generate_refresh_token()

    first = hash_refresh_token(token)

    assert first == hash_refresh_token(token)
    assert first != token
    assert TOKEN_HASH_FORMAT.fullmatch(first)


def test_different_tokens_have_different_hashes() -> None:
    assert hash_refresh_token("A" * 43) != hash_refresh_token("A" * 42 + "B")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "A" * 42,
        "A" * 44,
        "A" * 42 + "+",
        "A" * 42 + "/",
        "A" * 42 + "=",
        "A" * 42 + " ",
        "A" * 42 + "\n",
        "A" * 43 + "\n",
        "\n" + "A" * 43,
        "A" * 41 + "é",
        "A" * 41 + "\ud800",
        "A" * 42 + "٣",
        " " + "A" * 43,
        "Bearer " + "A" * 36,
    ],
)
def test_malformed_tokens_are_rejected_before_hashing(value: str) -> None:
    with pytest.raises(MalformedRefreshTokenError):
        hash_refresh_token(value)


def test_malformed_error_is_a_value_error_and_does_not_echo_the_value() -> None:
    with pytest.raises(ValueError) as excinfo:
        hash_refresh_token("secret-looking-but-malformed")

    assert isinstance(excinfo.value, MalformedRefreshTokenError)
    assert "secret-looking" not in str(excinfo.value)


def test_new_refresh_token_pairs_a_token_with_its_hash() -> None:
    issued = new_refresh_token()

    assert hash_refresh_token(issued.token) == issued.token_hash
    assert issued.token_hash != issued.token
    assert new_refresh_token().token != issued.token


def test_repr_does_not_reveal_the_token() -> None:
    issued = new_refresh_token()

    assert issued.token not in repr(issued)
    assert issued.token_hash in repr(issued)


def test_ttls_follow_the_accepted_decision() -> None:
    assert IDLE_TTL == timedelta(days=7)
    assert ABSOLUTE_TTL == timedelta(days=30)


def test_family_expiry_is_thirty_days_from_login() -> None:
    assert family_expires_at(NOW) == NOW + timedelta(days=30)


def test_idle_expiry_is_seven_days_while_the_family_has_time_left() -> None:
    family = family_expires_at(NOW)

    assert idle_expires_at(NOW, family) == NOW + timedelta(days=7)
    assert idle_expires_at(NOW + timedelta(days=20), family) == NOW + timedelta(days=27)


def test_idle_expiry_is_capped_by_the_family_expiry() -> None:
    family = family_expires_at(NOW)

    near_end = NOW + timedelta(days=28)
    assert idle_expires_at(near_end, family) == family
    assert idle_expires_at(family - timedelta(days=7), family) == family
    assert idle_expires_at(family, family) == family


@pytest.mark.parametrize("elapsed_days", [0, 1, 6, 7, 22, 23, 25, 29, 30, 31])
def test_idle_expiry_never_exceeds_the_family_expiry(elapsed_days: int) -> None:
    family = family_expires_at(NOW)

    assert idle_expires_at(NOW + timedelta(days=elapsed_days), family) <= family


def test_expiry_works_with_non_utc_aware_datetimes() -> None:
    tz = timezone(timedelta(hours=7))
    local = datetime(2026, 11, 24, 16, 30, tzinfo=tz)

    assert family_expires_at(local) == family_expires_at(NOW)
    assert idle_expires_at(local, family_expires_at(local)) == NOW + IDLE_TTL


def test_naive_datetimes_are_rejected() -> None:
    naive = datetime(2026, 11, 24, 9, 30)

    with pytest.raises(ValueError, match="timezone-aware"):
        family_expires_at(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        idle_expires_at(naive, NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        idle_expires_at(NOW, naive)
