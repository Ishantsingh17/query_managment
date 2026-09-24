"""One-time Gmail API authorization. Obtains an OAuth refresh token for the sender account and saves it to backend/.env.

Usage (from backend/):
    python -m app.notifications.gmail_oauth_setup path/to/client_secret.json
    python -m app.notifications.gmail_oauth_setup          # uses AEP_GMAIL_OAUTH_CLIENT_ID / _SECRET from .env

Opens your browser; sign in as the sender Gmail account and allow "Send email on your behalf".
Only the gmail.send scope is requested (the app cannot read mail).
"""
import http.server
import json
import re
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

from app.core.config import BACKEND_ROOT, get_settings

SCOPE = "https://www.googleapis.com/auth/gmail.send"
ENV_PATH = BACKEND_ROOT / ".env"


def _client_from_args() -> tuple[str, str]:
    if len(sys.argv) > 1:
        data = json.loads(open(sys.argv[1], encoding="utf-8").read())
        info = data.get("installed") or data.get("web") or {}
        return info["client_id"], info["client_secret"]
    s = get_settings()
    if not (s.gmail_oauth_client_id and s.gmail_oauth_client_secret):
        sys.exit("Provide the downloaded client_secret JSON path, or set AEP_GMAIL_OAUTH_CLIENT_ID and "
                 "AEP_GMAIL_OAUTH_CLIENT_SECRET in backend/.env.")
    return s.gmail_oauth_client_id, s.gmail_oauth_client_secret


def _set_env(values: dict[str, str]) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    for key, val in values.items():
        line = f"{key}={val}"
        if re.search(rf"^{key}=.*$", text, flags=re.M):
            text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    client_id, client_secret = _client_from_args()
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                result.update({k: v[0] for k, v in q.items()})
            ok = "code" in result
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(("<h3>Authorization complete - you can close this tab.</h3>" if ok
                              else f"<h3>Authorization failed: {result.get('error', 'unknown')}</h3>").encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "login_hint": get_settings().gmail_sender,
    })
    print("\nOpening your browser for Google sign-in. If it doesn't open, paste this URL:\n\n" + url + "\n")
    threading.Thread(target=server.handle_request, daemon=True).start()
    webbrowser.open(url)
    print("Waiting for authorization (up to 5 minutes)...")
    for _ in range(300):
        if result:
            break
        threading.Event().wait(1)
    server.server_close()
    if "code" not in result:
        sys.exit(f"Authorization not completed: {result.get('error', 'timed out')}")

    r = httpx.post("https://oauth2.googleapis.com/token", timeout=20, data={
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"})
    token = r.json()
    if "refresh_token" not in token:
        sys.exit(f"Google did not return a refresh token: {token}")
    _set_env({"AEP_GMAIL_OAUTH_CLIENT_ID": client_id, "AEP_GMAIL_OAUTH_CLIENT_SECRET": client_secret,
              "AEP_GMAIL_OAUTH_REFRESH_TOKEN": token["refresh_token"], "AEP_NOTIFICATION_PROVIDER": "gmail_api"})
    print(f"\nSaved Gmail API credentials to {ENV_PATH} and set AEP_NOTIFICATION_PROVIDER=gmail_api.")
    print("Next: python -m app.notifications.test_email you@example.com")


if __name__ == "__main__":
    main()
