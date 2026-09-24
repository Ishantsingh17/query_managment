"""Send a test notification with the configured provider and explain any failure.

Usage (from backend/):  python -m app.notifications.test_email you@example.com
"""
import socket
import sys

from app.core.config import get_settings
from app.notifications.service import ConsoleProvider, GmailApiProvider, GmailSmtpProvider, _html, get_provider


def _port_open(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=6).close()
        return True
    except OSError:
        return False


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m app.notifications.test_email you@example.com")
    to = sys.argv[1]
    s = get_settings()
    provider = get_provider()
    print(f"Provider setting : {s.notification_provider}")
    print(f"Active provider  : {type(provider).__name__}")
    print(f"Sender           : {s.gmail_sender}")

    if isinstance(provider, ConsoleProvider):
        print("\nConsole provider is active, so no email will be sent. Configure one of:")
        print("  AEP_NOTIFICATION_PROVIDER=gmail      + AEP_GMAIL_APP_PASSWORD   (needs SMTP ports 465/587 open)")
        print("  AEP_NOTIFICATION_PROVIDER=gmail_api  + run app.notifications.gmail_oauth_setup (HTTPS only)")
        return
    if isinstance(provider, GmailSmtpProvider) and not _port_open("smtp.gmail.com", s.gmail_smtp_port):
        other = 587 if s.gmail_smtp_port == 465 else 465
        print(f"\nCannot reach smtp.gmail.com:{s.gmail_smtp_port} — your network blocks outbound SMTP.")
        print(f"Port {other} is {'open — set AEP_GMAIL_SMTP_PORT=' + str(other) if _port_open('smtp.gmail.com', other) else 'blocked too'}.")
        print("On a blocked network use the Gmail API provider instead (see README, 'Email notifications').")
        return

    link = f"{s.app_base_url}/login"
    try:
        provider.send(to, "Audit Evidence Platform — test notification",
                      f"This is a test notification.\n\nOpen the application: {link}",
                      _html("Test notification", "Email notifications are configured correctly.", link, "Open application"))  # noqa: E501
    except Exception as exc:
        msg = str(exc)
        print(f"\nFAILED: {msg}")
        if "535" in msg or "Username and Password not accepted" in msg:
            print("Hint: use a 16-character App Password (not your Gmail password) and make sure 2-Step Verification is on.")
        if isinstance(provider, GmailApiProvider) and ("invalid_grant" in msg or "expired" in msg.lower()):
            print("Hint: the refresh token expired or was revoked (tokens for apps in 'Testing' expire after 7 days). "
                  "Re-run: python -m app.notifications.gmail_oauth_setup")
        sys.exit(1)
    print(f"\nSENT — check the inbox of {to} (and the Spam folder the first time).")


if __name__ == "__main__":
    main()
