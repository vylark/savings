"""Transactional email transport module.

Provides email dispatch capabilities using fastapi-mail with automatic mock/suppressed
delivery handling for local development and automated testing environments.
"""

import logging

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import SecretStr

from src.core.config import settings

logger = logging.getLogger("savings.mail")

# In-memory outbound email queue for testing assertion
outbox: list[dict[str, str]] = []


def clear_outbox() -> None:
    """Clears the test outbound email queue."""
    outbox.clear()


async def send_transactional_email(
    subject: str,
    recipient_email: str,
    body_text: str,
) -> None:
    """Dispatches transactional emails or enqueues in outbox if SUPPRESS_SEND is True.

    Args:
        subject: Email subject header.
        recipient_email: Destination recipient email address.
        body_text: Plaintext email body content.
    """
    if settings.SUPPRESS_SEND or not settings.SMTP_HOST:
        email_data = {
            "subject": subject,
            "recipient": recipient_email,
            "body": body_text,
        }
        outbox.append(email_data)
        logger.info(
            f"Email send suppressed (SUPPRESS_SEND=True or SMTP unconfigured). Target: {recipient_email}, Subject: {subject}"
        )
        return

    mail_config = ConnectionConfig(
        MAIL_USERNAME=settings.SMTP_USER or "",
        MAIL_PASSWORD=SecretStr(settings.SMTP_PASSWORD or ""),
        MAIL_FROM=settings.EMAILS_FROM_EMAIL,
        MAIL_PORT=settings.SMTP_PORT,
        MAIL_SERVER=settings.SMTP_HOST,
        MAIL_FROM_NAME=settings.EMAILS_FROM_NAME,
        MAIL_STARTTLS=True,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=bool(settings.SMTP_USER),
        VALIDATE_CERTS=True,
    )

    message = MessageSchema(
        subject=subject,
        recipients=[recipient_email],  # pyright: ignore[reportArgumentType]
        body=body_text,
        subtype=MessageType.plain,
    )

    fast_mail = FastMail(mail_config)
    await fast_mail.send_message(message)
