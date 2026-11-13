import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings

log = logging.getLogger("documind.email")


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class LogEmailSender:
    """Development only: writes the message to the log instead of sending it."""

    async def send(self, to: str, subject: str, body: str) -> None:
        log.info("[dev email] to=%s subject=%s\n%s", to, subject, body)


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self._s.smtp_user:
                smtp.login(self._s.smtp_user, self._s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "smtp":
        if not settings.smtp_host:
            raise RuntimeError("EMAIL_BACKEND=smtp requires SMTP_HOST")
        return SmtpEmailSender(settings)
    if settings.env == "production":
        raise RuntimeError("EMAIL_BACKEND=log is not allowed in production")
    return LogEmailSender()
