"""Unit tests for security, Fernet encryption, and TOTP helper utilities."""

from src.core.security import (
    decrypt_secret,
    encrypt_secret,
    generate_qr_code_base64,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
)


def test_encrypt_decrypt_secret() -> None:
    """Tests Fernet encryption and decryption of raw secret string."""
    plain_secret = generate_totp_secret()
    encrypted = encrypt_secret(plain_secret)

    assert encrypted != plain_secret
    decrypted = decrypt_secret(encrypted)
    assert decrypted == plain_secret


def test_totp_provisioning_uri_and_qr() -> None:
    """Tests OTPAuth provisioning URI generation and base64 QR code formatting."""
    plain_secret = generate_totp_secret()
    email = "test.user@example.com"

    uri = get_totp_uri(plain_secret, email, issuer_name="Savings Platform Test")
    assert "otpauth://totp/" in uri
    assert "test.user%40example.com" in uri
    assert "Savings%20Platform%20Test" in uri

    qr_b64 = generate_qr_code_base64(uri)
    assert qr_b64.startswith("data:image/png;base64,")


def test_verify_totp_code() -> None:
    """Tests TOTP passcode evaluation for valid and invalid inputs."""
    import pyotp

    plain_secret = generate_totp_secret()
    totp = pyotp.TOTP(plain_secret)
    valid_code = totp.now()

    assert verify_totp_code(plain_secret, valid_code) is True
    assert verify_totp_code(plain_secret, "000000") is False
