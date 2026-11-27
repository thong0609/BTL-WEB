"""Email normalization shared by registration, login and Google sign-in."""

MAX_EMAIL_LENGTH = 254


def normalize_email(email: str) -> str:
    """Trim surrounding whitespace and lowercase; reject empty or over-long values.

    This is not format validation. Format checks belong to the request schema.
    The length is checked after lowercasing because lowercasing can lengthen a string.
    """
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("Email must not be empty")
    if len(normalized) > MAX_EMAIL_LENGTH:
        raise ValueError("Email is too long")
    return normalized
