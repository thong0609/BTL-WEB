import pytest

from commerce_identity.emails import MAX_EMAIL_LENGTH, normalize_email


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("user@example.com", "user@example.com"),
        ("User@Example.COM", "user@example.com"),
        ("  user@example.com", "user@example.com"),
        ("user@example.com  ", "user@example.com"),
        ("\tuser@example.com\n", "user@example.com"),
        ("  MiXeD@Example.Com \n", "mixed@example.com"),
    ],
)
def test_trims_and_lowercases(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


def test_is_idempotent() -> None:
    once = normalize_email("  User@Example.COM ")
    assert normalize_email(once) == once


def test_inner_whitespace_is_kept() -> None:
    assert normalize_email("a b@example.com") == "a b@example.com"


def test_non_ascii_is_lowercased() -> None:
    assert normalize_email("ÀNH@Example.com") == "ành@example.com"


def test_uses_lowercase_not_casefold() -> None:
    # casefold would turn "ß" into "ss" and make different addresses collide.
    assert normalize_email("Straße@Example.com") == "straße@example.com"


@pytest.mark.parametrize("raw", ["", " ", "\t\n  "])
def test_rejects_empty(raw: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_email(raw)


def _email_of_length(length: int) -> str:
    domain = "@example.com"
    return "a" * (length - len(domain)) + domain


def test_accepts_exactly_max_length() -> None:
    value = _email_of_length(MAX_EMAIL_LENGTH)
    assert len(value) == 254
    assert normalize_email(value) == value


def test_rejects_one_over_max_length() -> None:
    with pytest.raises(ValueError, match="too long"):
        normalize_email(_email_of_length(MAX_EMAIL_LENGTH + 1))


def test_padding_does_not_count_toward_length() -> None:
    value = _email_of_length(MAX_EMAIL_LENGTH)
    assert normalize_email("  " + value + "  ") == value


def test_length_is_checked_after_lowercasing() -> None:
    # "İ" lowercases to two characters, so the length grows past the limit.
    value = "İ" * 127 + "@example.com"
    assert len(value) < MAX_EMAIL_LENGTH
    with pytest.raises(ValueError, match="too long"):
        normalize_email(value)
