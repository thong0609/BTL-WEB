from pathlib import Path

import pytest

from commerce_identity.settings import Settings

AUTH_VARIABLES = (
    "APP_ENV",
    "JWT_ISSUER",
    "JWT_PRIVATE_KEY_PEM",
    "OAUTH_COOKIE_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AUTH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def load(env_file: Path) -> Settings:
    return Settings(_env_file=env_file)  # type: ignore[call-arg]


def test_auth_settings_defaults(tmp_path: Path) -> None:
    settings = load(tmp_path / "missing.env")
    assert settings.jwt_issuer == "commerce-identity-service"
    assert settings.jwt_private_key_pem is None
    assert settings.oauth_cookie_secret is None
    assert settings.google_client_id is None
    assert settings.google_client_secret is None
    assert settings.google_redirect_uri is None


def test_auth_settings_read_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JWT_ISSUER=other-issuer\n"
        'JWT_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\\nAAAA\\n-----END PRIVATE KEY-----\\n"\n'
        "OAUTH_COOKIE_SECRET=cookie-secret-value\n"
        "GOOGLE_CLIENT_ID=client-id\n"
        "GOOGLE_CLIENT_SECRET=client-secret-value\n"
        "GOOGLE_REDIRECT_URI=http://localhost:3100/api/v1/auth/google/callback\n",
        encoding="utf-8",
    )
    settings = load(env_file)
    assert settings.jwt_issuer == "other-issuer"
    assert settings.google_client_id == "client-id"
    assert settings.google_redirect_uri == "http://localhost:3100/api/v1/auth/google/callback"
    assert settings.oauth_cookie_secret is not None
    assert settings.oauth_cookie_secret.get_secret_value() == "cookie-secret-value"
    assert settings.google_client_secret is not None
    assert settings.google_client_secret.get_secret_value() == "client-secret-value"


def test_pem_in_quotes_gets_real_newlines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'JWT_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\\nAAAA\\n-----END PRIVATE KEY-----\\n"\n',
        encoding="utf-8",
    )
    settings = load(env_file)
    assert settings.jwt_private_key_pem is not None
    value = settings.jwt_private_key_pem.get_secret_value()
    assert value == "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"


def test_pem_without_quotes_keeps_backslash_n_text(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JWT_PRIVATE_KEY_PEM=-----BEGIN PRIVATE KEY-----\\nAAAA\\n-----END PRIVATE KEY-----\\n\n",
        encoding="utf-8",
    )
    settings = load(env_file)
    assert settings.jwt_private_key_pem is not None
    value = settings.jwt_private_key_pem.get_secret_value()
    assert value == "-----BEGIN PRIVATE KEY-----\\nAAAA\\n-----END PRIVATE KEY-----\\n"


def test_secrets_are_hidden_from_repr(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JWT_PRIVATE_KEY_PEM=pem-secret-marker\n"
        "OAUTH_COOKIE_SECRET=cookie-secret-marker\n"
        "GOOGLE_CLIENT_SECRET=google-secret-marker\n",
        encoding="utf-8",
    )
    text = repr(load(env_file))
    for marker in ("pem-secret-marker", "cookie-secret-marker", "google-secret-marker"):
        assert marker not in text


def test_empty_issuer_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JWT_ISSUER=\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load(env_file)


def test_env_example_lists_auth_variables() -> None:
    example = Path("apps/identity-service/.env.example").read_text(encoding="utf-8")
    for name in AUTH_VARIABLES[1:]:
        assert name in example
