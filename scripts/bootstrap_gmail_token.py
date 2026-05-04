"""One-shot helper to obtain google_token.json with a refresh_token.

Usage:
    python scripts/bootstrap_gmail_token.py \
        --client-secret ./google_client_secret.json \
        --token ./google_token.json \
        --expected-email 17lunin021189@gmail.com

The script spins up a local loopback HTTP server, opens the Google consent
screen in your default browser, exchanges the authorization code for an
access + refresh token, sanity-checks the resulting Gmail profile against
--expected-email and writes the token JSON to disk.

No third-party OAuth libraries required (httpx + stdlib).
"""

from __future__ import annotations

import argparse
import http.server
import json
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

DEFAULT_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_client_secret(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = payload.get("installed") or payload.get("web")
    if not block:
        raise SystemExit(
            f"client secret at {path} has neither 'installed' nor 'web' section. "
            "Recreate the OAuth client as 'Desktop app'."
        )
    if not block.get("client_id") or not block.get("client_secret"):
        raise SystemExit(f"client secret at {path} is missing client_id or client_secret")
    return {
        "client_id": str(block["client_id"]),
        "client_secret": str(block["client_secret"]),
        "token_uri": str(block.get("token_uri") or TOKEN_URL),
        "auth_uri": str(block.get("auth_uri") or AUTH_URL),
    }


class _CodeHandler(http.server.BaseHTTPRequestHandler):
    received: dict[str, str] = {}
    expected_state: str = ""

    def log_message(self, format: str, *args) -> None:  # noqa: D401, ANN001
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth2callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not the oauth callback")
            return

        params = dict(urllib.parse.parse_qsl(parsed.query))
        if params.get("state") != self.expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"state mismatch; close this tab and try again")
            return

        if "error" in params:
            self.received.update({"error": params["error"]})
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"<h1>OAuth error</h1><p>{params['error']}</p>".encode("utf-8")
            )
            return

        code = params.get("code", "")
        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing code")
            return

        self.received.update({"code": code})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<h1>OK</h1><p>Authorization received. You can close this tab.</p>"
        )


def _wait_for_code(server: http.server.HTTPServer, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _CodeHandler.received:
            return dict(_CodeHandler.received)
        server.handle_request()
    raise SystemExit("timed out waiting for OAuth redirect")


def _exchange_code_for_tokens(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    token_uri: str,
) -> dict[str, str]:
    response = httpx.post(
        token_uri,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _verify_email(access_token: str, expected_email: str | None) -> str:
    response = httpx.get(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    response.raise_for_status()
    profile = response.json()
    actual = str(profile.get("emailAddress") or "").strip().lower()
    if expected_email and actual != expected_email.strip().lower():
        raise SystemExit(
            f"authorized as {actual!r} but expected {expected_email!r}. "
            "Re-run after signing into the correct Google account."
        )
    return actual


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a Gmail OAuth refresh token")
    parser.add_argument(
        "--client-secret",
        default="google_client_secret.json",
        help="Path to OAuth client secret JSON downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--token",
        default="google_token.json",
        help="Where to write the resulting token JSON.",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help="OAuth scope (default: gmail.readonly).",
    )
    parser.add_argument(
        "--expected-email",
        default=None,
        help="Optional: enforce that the authorized account matches this email address.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the browser; print the URL instead.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for the OAuth redirect (default: 300).",
    )
    args = parser.parse_args()

    client_secret_path = Path(args.client_secret)
    token_path = Path(args.token)
    if not client_secret_path.exists():
        raise SystemExit(f"client secret file not found: {client_secret_path}")

    creds = _read_client_secret(client_secret_path)

    port = _pick_free_port()
    redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"
    state = secrets.token_urlsafe(24)

    auth_params = {
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": args.scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"{creds['auth_uri']}?{urllib.parse.urlencode(auth_params)}"

    _CodeHandler.received = {}
    _CodeHandler.expected_state = state
    server = http.server.HTTPServer(("127.0.0.1", port), _CodeHandler)
    server.timeout = 1.0

    print(f"-> Local redirect listening on {redirect_uri}")
    print(f"-> Opening Google consent screen for scope: {args.scope}")
    if args.expected_email:
        print(f"-> Expecting account: {args.expected_email}")

    if args.no_browser:
        print("-> Open this URL manually in a browser logged into the right Google account:")
        print(auth_url)
    else:
        opened = webbrowser.open(auth_url, new=1, autoraise=True)
        if not opened:
            print("-> Failed to open browser automatically. Open this URL manually:")
            print(auth_url)

    received = _wait_for_code(server, timeout=args.timeout)
    server.server_close()

    if "error" in received:
        raise SystemExit(f"OAuth flow returned error: {received['error']}")

    tokens = _exchange_code_for_tokens(
        code=received["code"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        redirect_uri=redirect_uri,
        token_uri=creds["token_uri"],
    )

    if "refresh_token" not in tokens:
        raise SystemExit(
            "Google did not return a refresh_token. This usually means the account "
            "was authorized before. Revoke the app at https://myaccount.google.com/permissions "
            "and run the script again."
        )

    actual_email = _verify_email(tokens["access_token"], args.expected_email)

    payload = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens.get("token_type", "Bearer"),
        "scope": tokens.get("scope", args.scope),
        "expires_in": tokens.get("expires_in"),
        "client_id": creds["client_id"],
        "token_uri": creds["token_uri"],
        "email": actual_email,
    }
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"-> Wrote token JSON to {token_path}")
    print(f"-> Authorized account: {actual_email}")
    print("Done. Set GMAIL_TOKEN_PATH and GMAIL_CLIENT_SECRET_PATH in your env file.")


if __name__ == "__main__":
    sys.exit(main())
