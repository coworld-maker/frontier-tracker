"""
Fetch a Frontier login verification code from Gmail via IMAP.

Requires a Gmail *app password* (https://myaccount.google.com/apppasswords),
NOT the regular Google account password.
"""
from __future__ import annotations

import email as email_lib
import imaplib
import re
import time
from email.header import decode_header

IMAP_HOST = "imap.gmail.com"

# Senders Frontier uses for account emails
FRONTIER_SENDER_HINTS = ("flyfrontier", "frontier")

CODE_RE = re.compile(r"\b(\d{4,8})\b")


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _body_text(msg) -> str:
    chunks = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    chunks.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            chunks.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
    return "\n".join(chunks)


def _extract_code(subject: str, body: str) -> str | None:
    # Prefer a code in the subject line ("Your verification code is 123456")
    for text in (subject, body):
        # Strip HTML tags for cleaner matching
        text = re.sub(r"<[^>]+>", " ", text)
        # Look for a code near keywords first
        kw = re.search(r"(?:code|verification|passcode)\D{0,40}?(\d{4,8})", text, re.IGNORECASE)
        if kw:
            return kw.group(1)
    # Fallback: any standalone 6-digit number in the body
    m = re.search(r"\b(\d{6})\b", re.sub(r"<[^>]+>", " ", body))
    return m.group(1) if m else None


def fetch_frontier_otp(
    gmail_user: str,
    gmail_app_password: str,
    not_before_epoch: float,
    timeout_seconds: int = 120,
    poll_interval: int = 6,
) -> str | None:
    """Poll Gmail for a Frontier verification email newer than not_before_epoch.

    Returns the code string, or None on timeout.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            imap = imaplib.IMAP4_SSL(IMAP_HOST)
            imap.login(gmail_user, gmail_app_password)
            imap.select("INBOX")

            # Search recent messages (SINCE is date-granular, so filter by time below)
            date_str = time.strftime("%d-%b-%Y", time.localtime(not_before_epoch))
            _, data = imap.search(None, f'(SINCE "{date_str}")')
            ids = data[0].split()

            # Newest first
            for msg_id in reversed(ids[-30:]):
                _, msg_data = imap.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)

                sender = _decode(msg.get("From", "")).lower()
                if not any(h in sender for h in FRONTIER_SENDER_HINTS):
                    continue

                # Skip emails older than the login attempt
                date_tuple = email_lib.utils.parsedate_tz(msg.get("Date", ""))
                if date_tuple:
                    msg_epoch = email_lib.utils.mktime_tz(date_tuple)
                    if msg_epoch < not_before_epoch - 30:
                        continue

                subject = _decode(msg.get("Subject", ""))
                code = _extract_code(subject, _body_text(msg))
                if code:
                    imap.logout()
                    print(f"  OTP email found (subject: {subject!r}) — code extracted.")
                    return code

            imap.logout()
        except Exception as e:
            print(f"  Gmail poll error: {type(e).__name__}: {e}")

        time.sleep(poll_interval)

    print("  Timed out waiting for Frontier OTP email.")
    return None
