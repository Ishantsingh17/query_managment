"""Notification Service. Gmail is the development channel; the provider interface keeps workflow
logic independent of the mail system (swap for enterprise mail in production)."""
import base64
import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import quote
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import NotificationEvent

log = logging.getLogger(__name__)


class NotificationProvider(Protocol):
    channel: str

    def send(self, recipient: str, subject: str, text: str, html: str) -> None: ...


class ConsoleProvider:
    """Development default: records the notification and logs it instead of emailing."""
    channel = "GMAIL"
    status_on_success = "LOGGED"

    def send(self, recipient, subject, text, html):
        log.info("notification (console provider) to=%s subject=%s", recipient, subject)


def _mime(sender: str, recipient: str, subject: str, text: str, html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"Audit Evidence Platform <{sender}>"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


class GmailSmtpProvider:
    """Gmail SMTP with an App Password (needs outbound port 465 or 587)."""
    channel = "GMAIL"
    status_on_success = "SENT"

    def __init__(self, sender: str, app_password: str, port: int = 465):
        self.sender, self.app_password, self.port = sender, app_password.replace(" ", ""), port

    def send(self, recipient, subject, text, html):
        msg = _mime(self.sender, recipient, subject, text, html)
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=20) as smtp:
                smtp.login(self.sender, self.app_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP("smtp.gmail.com", self.port, timeout=20) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(self.sender, self.app_password)
                smtp.send_message(msg)


class GmailApiProvider:
    """Gmail API (HTTPS 443) using an OAuth refresh token — for networks that block SMTP."""
    channel = "GMAIL"
    status_on_success = "SENT"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def __init__(self, sender: str, client_id: str, client_secret: str, refresh_token: str):
        self.sender, self.client_id, self.client_secret, self.refresh_token = sender, client_id, client_secret, refresh_token

    def _access_token(self) -> str:
        r = httpx.post(self.TOKEN_URL, timeout=20, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.refresh_token, "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise RuntimeError(f"Gmail OAuth token refresh failed: {r.json().get('error_description') or r.text[:200]}")
        return r.json()["access_token"]

    def send(self, recipient, subject, text, html):
        raw = base64.urlsafe_b64encode(_mime(self.sender, recipient, subject, text, html).as_bytes()).decode()
        r = httpx.post(self.SEND_URL, json={"raw": raw}, timeout=20,
                       headers={"Authorization": f"Bearer {self._access_token()}"})
        if r.status_code >= 300:
            raise RuntimeError(f"Gmail API send failed ({r.status_code}): {r.text[:300]}")


def get_provider():
    s = get_settings()
    if s.notification_provider == "gmail_api" and s.gmail_oauth_refresh_token:
        return GmailApiProvider(s.gmail_sender, s.gmail_oauth_client_id, s.gmail_oauth_client_secret,
                                s.gmail_oauth_refresh_token)
    if s.notification_provider == "gmail" and s.gmail_app_password:
        return GmailSmtpProvider(s.gmail_sender, s.gmail_app_password, s.gmail_smtp_port)
    if s.notification_provider != "console":
        log.warning("notification provider %r is not fully configured; using console provider", s.notification_provider)
    return ConsoleProvider()


_provider_override = None


def set_provider(provider) -> None:
    global _provider_override
    _provider_override = provider


def _html(heading: str, body: str, link: str, cta: str, details: list[tuple[str, str]] | None = None,
          bullets: list[str] | None = None) -> str:
    rows = "".join(f'<tr><td style="color:#64728c;padding:3px 12px 3px 0">{k}</td><td style="font-weight:600">{v}</td></tr>'
                   for k, v in (details or []))
    items = "".join(f"<li>{b}</li>" for b in (bullets or []))
    return f"""<div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto;color:#0f1f3d">
<div style="background:#0f1f3d;color:#fff;padding:18px 24px;border-radius:10px 10px 0 0;font-weight:600">Audit Evidence Platform</div>
<div style="border:1px solid #e3e8f0;border-top:0;padding:24px;border-radius:0 0 10px 10px">
<h2 style="margin:0 0 8px;font-size:18px">{heading}</h2><p style="color:#52607a;line-height:1.5">{body}</p>
{f'<table style="font-size:13px;margin:0 0 12px">{rows}</table>' if rows else ''}
{f'<p style="margin:0 0 4px;font-weight:600">Missing evidence</p><ul style="margin:0 0 16px;color:#c21d1d">{items}</ul>' if items else ''}
<a href="{link}" style="display:inline-block;background:#1d56db;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">{cta}</a>
<p style="color:#8a96ab;font-size:12px;margin-top:20px">The link opens the Audit Evidence Platform sign-in page; after signing in you are taken to this request.</p></div></div>"""


# event_type -> (subject, heading, body, cta, audience role)
TEMPLATES = {
    "VALIDATION_REQUIRED": ("Action required: evidence missing · {rid}", "Evidence needs validation — {rid}",
                            "Request {rid} ({qt}) is missing required evidence. Please retry, upload or accept the "
                            "missing items so the request can move to SME approval.", "Open in Validation Portal", "VALIDATOR"),
    "REWORK_REQUESTED": ("Returned for rework · {rid}", "SME returned {rid} for rework",
                         "The Final Approver rejected the Evidence Review Package for {rid} ({qt}). Reason: {comment}",
                         "Open in Validation Portal", "VALIDATOR"),
    "REVIEW_PACKAGE_READY": ("Evidence Review Package ready · {rid}", "Evidence Review Package for {rid} is ready",
                             "The Evidence Review Package for request {rid} ({qt}) has been validated and is ready for your final review.",
                             "Review package", "SME"),
    "FINAL_RESPONSE_READY": ("Final Response Package approved · {rid}", "Your Final Response Package for {rid} is ready",
                             "Request {rid} ({qt}) has been approved by the SME. The Final Response Package is available in the application.",
                             "Open Final Response", "AUDITOR"),
}
EVENTS_BY_ROLE = {role: [e for e, t in TEMPLATES.items() if t[4] == role] for role in ("VALIDATOR", "SME", "AUDITOR")}


def login_link(next_path: str) -> str:
    """Every email link lands on the common sign-in page; the backend validates `next` after authentication."""
    return f"{get_settings().app_base_url}/login?next={quote(next_path, safe='/')}"


def recipient_for(user) -> str:
    """Dev recipients: per-role override > global override > the user's own address."""
    s = get_settings()
    role_override = {"VALIDATOR": s.notify_validator_email, "SME": s.notify_sme_email,
                     "AUDITOR": s.notify_auditor_email}.get(user.role, "")
    return role_override or s.notification_recipient_override or user.notification_email or user.email


def notify(session: Session, request_id: str, event_type: str, user, next_path: str,
           context: dict | None = None) -> NotificationEvent:
    provider = _provider_override or get_provider()
    ctx = context or {}
    subject_t, heading_t, body_t, cta, _ = TEMPLATES[event_type]
    fmt = {"rid": request_id, "qt": ctx.get("query_type_label", ""), "comment": ctx.get("comment") or "—"}
    to = recipient_for(user)
    link = login_link(next_path)
    event = NotificationEvent(notification_id=f"NTF-{uuid.uuid4().hex[:10].upper()}", request_id=request_id,
                              recipient=to, event_type=event_type, channel=provider.channel, status="PENDING",
                              application_link=link)
    details = [("Request ID", request_id), ("Query Type", ctx.get("query_type_label", ""))]
    if ctx.get("summary"):
        details.append(("Request", ctx["summary"]))
    missing = ctx.get("missing") or []
    try:
        body = body_t.format(**fmt)
        text = "\n".join([body, "", *[f"{k}: {v}" for k, v in details],
                          *(["", "Missing evidence:", *[f" - {m}" for m in missing]] if missing else []),
                          "", f"Sign in to open the request: {link}"])
        provider.send(to, subject_t.format(**fmt), text,
                      _html(heading_t.format(**fmt), body, link, cta, details, missing))
        event.status = getattr(provider, "status_on_success", "SENT")
        event.sent_at = datetime.now(timezone.utc)
    except Exception as exc:  # delivery failure must not break the workflow
        log.warning("notification failed", exc_info=True)
        event.status = "FAILED"
        event.error_message = str(exc)[:500]
    session.add(event)
    return event
