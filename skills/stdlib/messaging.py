"""skills.stdlib.messaging — email and Telegram messaging."""
from __future__ import annotations

from tools.comm.send_message import send_message


def send_email(
    to: str,
    subject: str = "",
    body: str = "",
    html: bool = False,
) -> dict:
    """Send an email via SMTP. Configure SMTP_* in .env."""
    return send_message(backend="email", to=to, subject=subject, body=body, html=html)


def send_telegram(body: str, chat_id: str = "") -> dict:
    """Send a Telegram message. Configure TELEGRAM_* in .env."""
    return send_message(backend="telegram", body=body, chat_id=chat_id)


__all__ = ["send_email", "send_telegram", "send_message"]
