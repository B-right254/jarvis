"""
send_message — outbound communication organ.

Lets Jarvis reach out to the user (or a contact) after completing a long
background task — not just show a toast they might miss.

Backends
--------
email       SMTP via stdlib ``smtplib``.  Configure SMTP_* in .env.
            Works with Gmail (use an App Password, not your account password),
            Outlook.com, and any SMTP relay.
telegram    Sends a message to a Telegram chat via the Bot API.
            Requires TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env.

Quick-start: Gmail
------------------
1. Enable 2-Step Verification on your Google account.
2. Create an App Password at https://myaccount.google.com/apppasswords.
3. Add to .env:
       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=587
       SMTP_USER=you@gmail.com
       SMTP_PASS=<app-password>

Quick-start: Telegram
---------------------
1. Message @BotFather on Telegram → /newbot → copy the token.
2. Add TELEGRAM_BOT_TOKEN=<token> to .env.
3. Send any message to your bot, then run:
       GET https://api.telegram.org/bot<token>/getUpdates
   Copy the ``chat.id`` value → TELEGRAM_CHAT_ID=<id>.
"""

from __future__ import annotations

import logging
import smtplib
import urllib.request
import urllib.parse
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import settings

logger = logging.getLogger(__name__)


# ── email ─────────────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str, html: bool) -> dict:
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    user = settings.SMTP_USER
    password = settings.SMTP_PASS
    from_addr = settings.SMTP_FROM or user

    if not user or not password:
        return {
            "success": False,
            "error": (
                "SMTP credentials not configured. "
                "Set SMTP_USER and SMTP_PASS in .env."
            ),
        }
    if not to:
        return {"success": False, "error": "recipient 'to' is required for email"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = from_addr
    msg["To"] = to

    mime_type = "html" if html else "plain"
    msg.attach(MIMEText(body, mime_type, "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to], msg.as_string())
        logger.info(f"send_message (email): sent to {to} — '{subject}'")
        return {"success": True, "backend": "email", "to": to, "subject": subject}
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "error": "SMTP authentication failed. Check SMTP_USER / SMTP_PASS in .env.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── telegram ──────────────────────────────────────────────────────────────────

def _send_telegram(body: str, chat_id: str) -> dict:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return {
            "success": False,
            "error": "TELEGRAM_BOT_TOKEN not set in .env.",
        }
    target = chat_id or settings.TELEGRAM_CHAT_ID
    if not target:
        return {
            "success": False,
            "error": "No chat_id provided and TELEGRAM_CHAT_ID not set in .env.",
        }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": target, "text": body, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read())
        if data.get("ok"):
            logger.info(f"send_message (telegram): sent to chat {target}")
            return {"success": True, "backend": "telegram", "chat_id": target}
        return {"success": False, "error": data.get("description", "Unknown Telegram error")}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── public API ────────────────────────────────────────────────────────────────

def send_message(
    backend: str = "email",
    to: str = "",
    subject: str = "",
    body: str = "",
    html: bool = False,
    chat_id: str = "",
) -> dict:
    """
    Send an outbound message to the user or a contact.

    Parameters
    ----------
    backend : str
        ``email`` or ``telegram`` (default ``email``).
    to : str
        Recipient email address (required for email backend).
    subject : str
        Email subject line.  Ignored for Telegram.
    body : str
        Message body / content.
    html : bool
        Send body as HTML for email (default False = plain text).
    chat_id : str
        Telegram chat ID override.  Falls back to ``TELEGRAM_CHAT_ID`` in .env.

    Returns
    -------
    dict
        ``{"success": bool, "backend": str, ...}``
    """
    if not body:
        return {"success": False, "error": "body cannot be empty"}

    logger.info(f"send_message: backend={backend}")

    if backend == "email":
        return _send_email(to, subject, body, html)
    elif backend == "telegram":
        return _send_telegram(body, chat_id)
    else:
        return {"success": False, "error": f"Unknown backend '{backend}'. Use 'email' or 'telegram'."}
