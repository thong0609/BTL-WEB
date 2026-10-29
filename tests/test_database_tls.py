import ssl

import pytest

from commerce_backend_common.database import DatabaseConfigurationError, ssl_context


def test_custom_ca_keeps_certificate_and_hostname_verification(tmp_path):
    roots = ssl.create_default_context().get_ca_certs(binary_form=True)
    assert roots, "This test requires at least one installed system CA"
    ca_file = tmp_path / "trusted-ca.crt"
    ca_file.write_text(ssl.DER_cert_to_PEM_cert(roots[0]), encoding="ascii")
    context = ssl_context("verify-full", "database.example", ca_file)
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert roots[0] in context.get_ca_certs(binary_form=True)


@pytest.mark.parametrize("exists", [True, False])
def test_missing_or_invalid_ca_fails_closed(tmp_path, exists):
    ca_file = tmp_path / "invalid.crt"
    if exists:
        ca_file.write_text("not a certificate", encoding="ascii")
    with pytest.raises(DatabaseConfigurationError):
        ssl_context("verify-full", "database.example", ca_file)


def test_loopback_test_database_does_not_require_a_ca(tmp_path):
    assert ssl_context("disable", "127.0.0.1", tmp_path / "unused.crt") is False
