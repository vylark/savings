"""Security, encryption, and Multi-Factor Authentication (TOTP 2FA) helper module.

Provides Fernet symmetric encryption and decryption for sensitive tokens at rest,
TOTP secret provisioning, QR code payload generation, and OTP validation helpers.
"""

import base64
import io

import pyotp
import qrcode
import qrcode.constants
from cryptography.fernet import Fernet

from src.core.config import settings


def _get_fernet_cipher() -> Fernet:
    """Constructs Fernet cipher instance using application TOTP_SECRET_KEY configuration.

    Returns:
        Fernet cipher instance configured with application encryption key.
    """
    return Fernet(settings.TOTP_SECRET_KEY.encode("utf-8"))


def encrypt_secret(plain_secret: str) -> str:
    """Encrypts raw plaintext secret using Fernet symmetric encryption.

    Args:
        plain_secret: Plaintext TOTP secret string.

    Returns:
        Encrypted token string.
    """
    cipher = _get_fernet_cipher()
    encrypted_bytes = cipher.encrypt(plain_secret.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_secret(encrypted_secret: str) -> str:
    """Decrypts Fernet-encrypted secret string into raw plaintext secret.

    Args:
        encrypted_secret: Encrypted TOTP secret token.

    Returns:
        Decrypted plaintext TOTP secret string.
    """
    cipher = _get_fernet_cipher()
    decrypted_bytes = cipher.decrypt(encrypted_secret.encode("utf-8"))
    return decrypted_bytes.decode("utf-8")


def generate_totp_secret() -> str:
    """Generates a random base32 TOTP secret string.

    Returns:
        Random base32 TOTP secret string.
    """
    return pyotp.random_base32()


def get_totp_uri(plain_secret: str, email: str, issuer_name: str = "Savings Platform") -> str:
    """Generates an OTPAuth URI string for standard authenticator applications.

    Args:
        plain_secret: Plaintext base32 TOTP secret.
        email: User email address identifier.
        issuer_name: Platform issuer name displayed in authenticator app.

    Returns:
        OTPAuth provisioning URI string.
    """
    totp = pyotp.TOTP(plain_secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer_name)


def generate_qr_code_base64(provisioning_uri: str) -> str:
    """Generates a PNG QR code image as a base64 encoded data URI string.

    Args:
        provisioning_uri: OTPAuth provisioning URI string.

    Returns:
        Base64-encoded PNG data URI string.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, kind="png")
    b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return f"data:image/png;base64,{b64_str}"


def verify_totp_code(plain_secret: str, code: str, valid_window: int = 1) -> bool:
    """Verifies a 6-digit TOTP code against the plaintext base32 TOTP secret.

    Args:
        plain_secret: Plaintext base32 TOTP secret.
        code: 6-digit TOTP passcode string submitted by user.
        valid_window: Allowable time drift window multiplier.

    Returns:
        True if the OTP code is valid, False otherwise.
    """
    totp = pyotp.TOTP(plain_secret)
    return totp.verify(code, valid_window=valid_window)
