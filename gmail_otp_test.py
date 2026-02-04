# gmail_otp_test.py
import os
import re
import base64
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_FILE = os.environ.get("GMAIL_CREDENTIALS", "./gmail_credentials.json")
TOKEN_FILE = os.environ.get("GMAIL_TOKEN", "./gmail_token.json")


def get_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            # opens browser for consent on first run
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _walk_parts(payload):
    """Flatten Gmail payload parts recursively."""
    if not payload:
        return []
    if "parts" in payload:
        out = []
        for p in payload["parts"]:
            out.extend(_walk_parts(p))
        return out
    return [payload]


def _extract_text_from_msg(msg_full):
    """Extract text/plain or text/html bodies into a single string."""
    payload = msg_full.get("payload", {}) or {}
    parts = _walk_parts(payload)

    texts = []
    for p in parts:
        mime = (p.get("mimeType") or "").lower()
        if mime not in ("text/plain", "text/html"):
            continue
        data = ((p.get("body") or {}).get("data"))  # base64url
        if not data:
            continue
        try:
            raw = base64.urlsafe_b64decode(data + "==")
            texts.append(raw.decode("utf-8", errors="ignore"))
        except Exception:
            continue

    # Sometimes body is directly on payload (no parts)
    if not texts:
        mime = (payload.get("mimeType") or "").lower()
        data = ((payload.get("body") or {}).get("data"))
        if mime in ("text/plain", "text/html") and data:
            try:
                raw = base64.urlsafe_b64decode(data + "==")
                texts.append(raw.decode("utf-8", errors="ignore"))
            except Exception:
                pass

    return "\n".join(texts)


def fetch_latest_otp(service, newer_than="60m"):
    """
    Fetch latest 6-digit OTP from Amazon A to Z verification email.
    Adjust query if your subject/from differs.
    """
    query = (
        'from:no-reply@amazon.work '
        'subject:"Amazon A to Z login verification code" '
        f'newer_than:{newer_than}'
    )

    res = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
    msgs = res.get("messages", [])
    if not msgs:
        return None

    # pick newest by internalDate
    newest_id = None
    newest_ts = -1
    for m in msgs:
        meta = service.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
        ts_ms = int(meta.get("internalDate", "0"))
        if ts_ms > newest_ts:
            newest_ts = ts_ms
            newest_id = m["id"]

    # get full message
    msg = service.users().messages().get(userId="me", id=newest_id, format="full").execute()

    # 1) try snippet
    snippet = msg.get("snippet", "") or ""
    m1 = re.search(r"\b(\d{6})\b", snippet)
    if m1:
        return m1.group(1)

    # 2) fall back to body text
    body_text = _extract_text_from_msg(msg)
    m2 = re.search(r"\b(\d{6})\b", body_text)
    if m2:
        return m2.group(1)

    return None


if __name__ == "__main__":
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Missing {CREDENTIALS_FILE}. Put your downloaded OAuth Desktop JSON there."
        )

    svc = get_service()
    otp = fetch_latest_otp(svc, newer_than="60m")
    print("OTP =", otp)
