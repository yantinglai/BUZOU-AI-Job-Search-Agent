from __future__ import annotations

import os
import re
import json
import time
import random
import traceback
import smtplib
import urllib.request
import urllib.error
from datetime import datetime
from email.message import EmailMessage

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

# Gmail API (optional)
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# ============================================================
# Config
# ============================================================
MODE = os.environ.get("MODE", "interactive").lower().strip()
# MODE = "auto" or "interactive"

TYPE_DELAY_MS = int(os.environ.get("TYPE_DELAY_MS", "10"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

AUTO_SUBMIT = (MODE == "auto")
ABOUTME_ORIGIN = "https://prod.aboutme.talent.amazon.dev"

SKIP_INTERNSHIP = True
DEBUG_FILTERING = True
FILTER_DEBUG_PREVIEW_CHARS = 280

# Email settings (for high score notifications / login failures)
EMAIL_TO = os.environ.get("EMAIL_TO", "laiyanting.neu@gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM", os.environ.get("SMTP_USER", ""))
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

HIGH_SCORE_THRESHOLD = int(os.environ.get("HIGH_SCORE_THRESHOLD", "8"))
ENRICH_APPLY_NOW = os.environ.get("ENRICH_APPLY_NOW", "1") == "1"

# Gmail OTP integration (optional)
ENABLE_GMAIL_OTP = os.environ.get("ENABLE_GMAIL_OTP", "0") == "1"
GMAIL_CREDENTIALS = os.environ.get(
    "GMAIL_CREDENTIALS", "./gmail_credentials.json")
GMAIL_TOKEN = os.environ.get("GMAIL_TOKEN", "./gmail_token.json")


# ============================================================
# Candidate profile
# ============================================================
CANDIDATE_PROFILE = """
I am a software engineer on AWS Redshift Vacuum and storage data plane.
I designed a sliding window anomaly detector for vacuum transactions and enabled real time SEV creation, reducing response time from 2 months to 1 week.
I improved the Jenkins to Hydra test migration tool, raising conversion rate from 20% to 90%.
I built swarm system tests and performance tests for Vacuum workflows and found critical bugs before release.
I designed sortedness effectiveness metrics for AutoVacuum Sort and Recluster and optimized block overlap detection from N^2 to N log N on 10TB tables.
My next step is AI infrastructure and platform engineering: scalable systems, data and model pipelines, reliability, performance, and observability.
""".strip()


# ============================================================
# Location policy helpers
# ============================================================
BAY_AREA_HINTS = [
    "bay area", "san francisco", "sf", "south san francisco", "san mateo",
    "burlingame", "palo alto", "east palo alto", "menlo park", "mountain view",
    "sunnyvale", "santa clara", "san jose", "cupertino", "fremont", "milpitas",
    "los gatos", "campbell", "union city", "oakland", "berkeley", "emeryville",
    "hayward", "redwood city"
]

FULLSTACK_STRONG_KEYWORDS = ["fullstack", "full stack", "full-stack"]

FRONTEND_HARD_SIGNALS = [
    "frontend engineer", "front end engineer", "front-end engineer",
    "ui engineer", "ux engineer",
    "react native", "ios engineer", "android engineer", "component library"
]

FRONTEND_SOFT_KEYWORDS = [
    "react", "angular", "vue", "javascript", "typescript",
    "css", "html", "webpack", "node.js", "next.js",
    "mobile", "ios", "android", "swift", "kotlin"
]

BACKEND_STRONG_KEYWORDS = [
    "backend", "back end", "back-end",
    "distributed", "microservice", "service", "services",
    "api", "rpc", "grpc",
    "storage", "database", "sql", "query", "scheduler",
    "pipeline", "etl", "streaming", "kafka", "spark", "flink",
    "reliability", "availability", "latency", "throughput",
    "observability", "metrics", "logging", "tracing", "oncall", "incident",
    "infrastructure", "platform", "systems", "linux",
    "aws", "s3", "dynamodb", "ec2", "eks", "lambda",
    "java", "c++", "golang", "rust", "python", "redshift"
]

SCORE_KEYWORDS = [
    "platform", "infrastructure", "distributed", "systems", "scalability",
    "reliability", "availability", "latency", "throughput", "observability",
    "metrics", "tracing", "logging", "oncall", "incident", "performance",
    "data", "pipeline", "etl", "streaming", "kafka", "spark", "flink",
    "database", "storage", "sql", "query", "index", "cache",
    "ml", "machine learning", "model", "inference", "training", "llm", "genai",
    "aws", "s3", "dynamodb", "ecs", "eks", "ec2", "lambda", "sagemaker"
]

NEGATIVE_SCORE_KEYWORDS = [
    "react", "angular", "vue", "css", "html", "mobile", "ios", "android",
    "design system", "component library", "ux", "ui"
]


# ============================================================
# URL config
# ============================================================
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def encode_filter_values(values: list[str]) -> str:
    return "%7C%7C%7C".join(v.replace(" ", "%2520") for v in values)


states = ["California", "Washington", "New York"]
cities = [
    "Seattle", "Bellevue", "New York", "San Francisco", "Redmond",
    "Culver City", "Sunnyvale", "Santa Clara", "Kirkland",
    "Santa Monica", "San Diego", "Irvine", "Los Angeles",
    "Cupertino", "Palo Alto", "East Palo Alto", "Union City",
    "Burbank", "Los Gatos", "Mountain View", "San Jose"
]

SEARCH_URL = (
    "https://prod.internal-transfer.talent.amazon.dev/find-roles/search"
    "?sort=relevance"
    "&categories=Software%2520Development%7C%7C%7CMachine%2520Learning%2520Science"
    f"&cities={encode_filter_values(cities)}"
    "&countries=USA"
    "&levels=4"
    f"&states={encode_filter_values(states)}"
)


# ============================================================
# Auto Login helper (username)
# ============================================================
def try_click_then_fill_username(page, username: str) -> bool:
    user = page.locator("[data-testid='username-input']").first
    try:
        user.wait_for(state="visible", timeout=20000)
    except PWTimeout:
        return False
    try:
        user.click(timeout=3000)
        user.focus(timeout=3000)
    except Exception:
        pass

    try:
        user.fill(username, timeout=5000)
        return True
    except Exception as e:
        print(f"[{ts()}] username fill failed after click: {e}")
        return False


def detect_username_input(page, timeout_ms=2000) -> bool:
    user = page.locator("[data-testid='username-input']").first
    try:
        user.wait_for(state="visible", timeout=timeout_ms)
        return True
    except PWTimeout:
        return False


# ============================================================
# Email helper
# ============================================================
def can_email() -> bool:
    return bool(SMTP_USER and SMTP_PASS and EMAIL_TO)


def send_email(subject: str, body: str) -> bool:
    if not can_email():
        print(f"[{ts()}] Email not configured. Set SMTP_USER, SMTP_PASS, EMAIL_TO.")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM or SMTP_USER
    msg["To"] = EMAIL_TO
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"[{ts()}] Email sent: {subject}")
        return True
    except Exception as e:
        print(f"[{ts()}] Email send failed: {e}")
        return False


# ============================================================
# Gmail API (optional)
# ============================================================
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    if not os.path.exists(GMAIL_CREDENTIALS):
        raise FileNotFoundError(
            f"Missing Gmail OAuth credentials file: {GMAIL_CREDENTIALS}")

    creds = None
    if os.path.exists(GMAIL_TOKEN):
        creds = Credentials.from_authorized_user_file(
            GMAIL_TOKEN, GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                GMAIL_CREDENTIALS, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GMAIL_TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_amazon_otp(service, newer_than="15m"):
    query = f"from:no-reply@amazon.work subject:\"Amazon A to Z login verification code\" newer_than:{newer_than}"
    results = service.users().messages().list(
        userId="me", q=query, maxResults=5).execute()
    msgs = results.get("messages", [])
    if not msgs:
        return None

    newest_id = None
    newest_ts = -1
    for m in msgs:
        meta = service.users().messages().get(
            userId="me", id=m["id"], format="metadata").execute()
        ts_ms = int(meta.get("internalDate", "0"))
        if ts_ms > newest_ts:
            newest_ts = ts_ms
            newest_id = m["id"]

    msg = service.users().messages().get(userId="me", id=newest_id).execute()
    snippet = msg.get("snippet", "") or ""
    m = re.search(r"\b(\d{6})\b", snippet)
    return m.group(1) if m else None


# ============================================================
# Login detection + handler
# ============================================================
def try_fill_otp_code(page, gmail_service, out_dir: str, newer_than="60m") -> bool:
    if not gmail_service:
        return False

    try:
        verify_btn = page.get_by_role(
            "button", name=re.compile(r"verify\s*identity", re.I)).first
        code_input = page.locator(
            "input#code, input[name='code'], "
            "input[placeholder*='enter code' i], "
            "input[aria-label*='code' i], "
            "input[inputmode='numeric'], input[type='tel']"
        ).first

        verify_btn.wait_for(state="visible", timeout=1500)
        code_input.wait_for(state="visible", timeout=1500)
    except Exception:
        return False

    print(f"[{ts()}] OTP page detected. Polling Gmail for OTP...")

    otp_code = None
    for _ in range(18):
        otp_code = fetch_amazon_otp(gmail_service, newer_than=newer_than)
        if otp_code:
            break
        page.wait_for_timeout(5000)

    if not otp_code:
        print(f"[{ts()}] OTP not found in Gmail (newer_than={newer_than}).")
        return False

    print(f"[{ts()}] Found OTP: {otp_code}")

    try:
        code_input.click(timeout=2000)
    except Exception:
        pass

    try:
        code_input.fill(otp_code, timeout=5000)
    except Exception:
        code_input.type(otp_code, delay=TYPE_DELAY_MS)

    try:
        trust_cb = page.locator("input[type='checkbox']").first
        if trust_cb.count() > 0:
            trust_cb.check()
    except Exception:
        pass

    try:
        if out_dir:
            page.screenshot(path=os.path.join(
                out_dir, f"otp_filled_{ts().replace(':','')}.png"), full_page=True)
    except Exception:
        pass

    verify_btn.click(timeout=8000)
    page.wait_for_timeout(1500)
    print(f"[{ts()}] OTP submitted (Verify identity clicked).")
    return True


def is_logged_in_search_page(page) -> bool:
    try:
        if page.locator("#search-navigation-sidebar-section").count() > 0:
            return True
        if page.locator("div[id^='role-card-']").count() > 0:
            return True
    except Exception:
        pass
    return False


def try_password_step(page) -> bool:
    pw = os.environ.get("AMAZON_PASSWORD", "").strip()
    if not pw:
        print(f"[{ts()}] AMAZON_PASSWORD not set; skip password step.")
        return False

    password = page.locator(
        "input[type='password'], input#password, input[name='password']").first

    try:
        password.wait_for(state="visible", timeout=2500)
    except PWTimeout:
        return False

    try:
        password.click(timeout=1500)
    except Exception:
        pass

    try:
        password.fill(pw, timeout=5000)
    except Exception as e:
        print(f"[{ts()}] password fill failed: {e}")
        return False

    submit_candidates = [
        page.get_by_role("button", name=re.compile(
            r"sign\s*in|log\s*in|continue|next", re.I)),
        page.locator("button[type='submit']"),
        page.locator("input[type='submit']"),
    ]
    for btn in submit_candidates:
        try:
            if btn.count() > 0:
                btn.first.click(timeout=5000)
                page.wait_for_timeout(1200)
                print(f"[{ts()}] Password submitted.")
                return True
        except Exception:
            continue

    try:
        password.press("Enter")
        page.wait_for_timeout(1200)
        print(f"[{ts()}] Password submitted by Enter.")
        return True
    except Exception as e:
        print(f"[{ts()}] password submit failed: {e}")
        return False


def try_select_mfa_destination(page, prefer_email=True) -> bool:
    try:
        page.locator("form#selectPhone_form").wait_for(
            state="visible", timeout=1500)
    except Exception:
        return False

    try:
        radios = page.locator(
            "input[type='radio'][name='otpDestinationSelectionIndex']")
        if radios.count() <= 0:
            return False

        chosen = False
        if prefer_email:
            email_radio = page.locator(
                "input[type='radio'][name='otpDestinationSelectionIndex'][value='2']"
            )
            if email_radio.count() > 0:
                email_radio.first.check()
                chosen = True

        if not chosen:
            radios.last.check()

        page.get_by_role("button", name=re.compile(
            r"continue|next", re.I)).click(timeout=5000)
        page.wait_for_timeout(900)
        print(f"[{ts()}] MFA destination selected and continued.")
        return True
    except Exception as e:
        print(f"[{ts()}] MFA destination step failed: {e}")
        return False


def handle_login(page, out_dir: str, gmail_service=None) -> bool:
    try:
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
    except Exception:
        pass

    if is_logged_in_search_page(page):
        print(f"[{ts()}] Already logged in on search page.")
        return True

    print(f"[{ts()}] Not logged in. current url={page.url}")

    username = os.environ.get("AMAZON_USERNAME", "").strip()
    if not username:
        print(f"[{ts()}] AMAZON_USERNAME not set; manual login required.")

    max_loops = 40
    for i in range(max_loops):
        if is_logged_in_search_page(page):
            print(f"[{ts()}] Logged in detected.")
            return True

        try:
            ui_user = page.locator("[data-testid='username-input']").count()
            ui_pw = page.locator(
                "input[type='password'], input#password, input[name='password']").count()
            print(
                f"[{ts()}] [login-loop {i}] url={page.url} user_inputs={ui_user} pw_inputs={ui_pw}")
        except Exception:
            pass

        try:
            if username and detect_username_input(page, timeout_ms=1200):
                ok_user = try_click_then_fill_username(page, username)
                if ok_user:
                    btns = [
                        page.get_by_role("button", name=re.compile(
                            r"continue|next", re.I)),
                        page.locator("button[type='submit']"),
                    ]
                    clicked = False
                    for b in btns:
                        try:
                            if b.count() > 0:
                                b.first.click(timeout=5000)
                                clicked = True
                                break
                        except Exception:
                            continue
                    if clicked:
                        print(f"[{ts()}] Username submitted.")
                        page.wait_for_timeout(800)
                        continue
        except Exception as e:
            print(f"[{ts()}] username step exception: {e}")

        try:
            if try_password_step(page):
                page.wait_for_timeout(1200)
                continue
        except Exception as e:
            print(f"[{ts()}] password step exception: {e}")

        try:
            if try_select_mfa_destination(page, prefer_email=True):
                page.wait_for_timeout(800)
                continue
        except Exception as e:
            print(f"[{ts()}] MFA step exception: {e}")

        try:
            if try_fill_otp_code(page, gmail_service, out_dir, newer_than="60m"):
                page.wait_for_timeout(1500)
                continue
        except Exception as e:
            print(f"[{ts()}] OTP step exception: {e}")

        page.wait_for_timeout(800)

    print(f"[{ts()}] Auto login steps not completed within loop window. Manual login required.")
    input("Finish login/AEA in the opened browser, then press Enter here...")

    try:
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
    except Exception:
        pass

    ok = is_logged_in_search_page(page)
    print(f"[{ts()}] Login status after manual step: {ok}")
    return ok


# ============================================================
# Right panel helpers
# ============================================================
def extract_job_id_from_text(s: str):
    if not s:
        return None
    m = re.search(r"\bJob\s*ID\b\s*[:#]?\s*(\d{6,})\b", s, re.IGNORECASE)
    return m.group(1) if m else None


def find_right_panel_container(page):
    anchor = page.locator("#search-match-role-thingsToConsider").first
    anchor.wait_for(timeout=60000)

    for up in range(1, 14):
        cand = anchor.locator(f"xpath=ancestor::div[{up}]")
        try:
            txt = clean(cand.inner_text(timeout=1500) or "")
        except Exception:
            continue
        if re.search(r"\bJob\s*ID\b\s*[:#]?\s*\d{6,}\b", txt, re.IGNORECASE):
            return cand

    return anchor.locator("xpath=ancestor::div[8]")


def wait_job_id_in_right_panel(page, right_container, timeout_ms=25000):
    deadline = datetime.now().timestamp() + timeout_ms / 1000.0
    last_preview = ""
    while datetime.now().timestamp() < deadline:
        try:
            last_preview = clean(
                right_container.inner_text(timeout=1500) or "")
        except Exception:
            last_preview = ""
        jid = extract_job_id_from_text(last_preview)
        if jid:
            return jid, last_preview
        page.wait_for_timeout(200)
    return None, last_preview


def has_request_informational(right_container) -> bool:
    btn = right_container.get_by_role("button", name="Request informational")
    return btn.count() > 0


def has_apply_now(right_container) -> bool:
    btn = right_container.get_by_role(
        "button", name=re.compile(r"apply\s*now", re.I))
    if btn.count() > 0:
        return True
    btn2 = right_container.get_by_role(
        "button", name=re.compile(r"^\s*apply\s*$", re.I))
    return btn2.count() > 0


def decide_role_action(right_container) -> str:
    if has_request_informational(right_container):
        return "INFO"
    if has_apply_now(right_container):
        return "APPLY_NOW"
    return "SKIP"


# ✅ Return to the exact current search URL (keeps page=2,3,...)
def post_return_to_search(page, out_dir: str, filename: str, return_url: str):
    try:
        page.screenshot(path=os.path.join(out_dir, filename), full_page=True)
    except Exception:
        pass
    try:
        page.goto(return_url, wait_until="domcontentloaded")
        page.wait_for_timeout(900)
    except Exception:
        pass


def ensure_on_search_page(page):
    if not is_logged_in_search_page(page):
        try:
            page.goto(SEARCH_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(900)
        except Exception:
            pass


# ============================================================
# Extract JD-like text
# ============================================================
JD_KEEP_KEYWORDS = [
    "build", "design", "own", "deliver", "develop", "maintain", "operate", "scale",
    "improve", "optimize", "monitor", "measure", "debug", "deploy",
    "distributed", "reliability", "availability", "latency", "performance",
    "observability", "monitoring", "metrics", "logging", "tracing", "incident",
    "data integrity", "data quality", "pipeline", "platform", "infrastructure",
    "machine learning", "model", "training", "inference", "feature", "ranking",
    "fraud", "trust", "integrity", "anomaly", "detection",
    "aws", "s3", "dynamodb", "kafka", "spark", "airflow", "python", "java", "c++",
    "sql", "etl", "billing", "payment", "pricing", "audit", "compliance"
]


def extract_jd_like_text(body_text: str, max_chars: int = 4500) -> str:
    t = clean(body_text or "")
    if not t:
        return ""
    parts = re.split(r"(?<=[\.\!\?])\s+|\n+", t)
    kept = []
    for p in parts:
        pl = p.lower()
        if any(k in pl for k in JD_KEEP_KEYWORDS):
            if len(p) >= 40:
                kept.append(p)
    out = " ".join(kept).strip()
    if not out:
        out = t[:max_chars]
    return clean(out)[:max_chars]


# ============================================================
# Role filtering logic
# ============================================================
def is_bay_area_from_text(text: str) -> bool:
    tl = (text or "").lower()
    return any(h in tl for h in BAY_AREA_HINTS)


def score_hits(blob: str, keywords: list[str]) -> int:
    blob = (blob or "").lower()
    return sum(1 for kw in keywords if kw in blob)


def frontend_diagnose(title: str, role_context: str):
    blob = " ".join([title or "", role_context or ""]).lower()
    has_fullstack = any(kw in blob for kw in FULLSTACK_STRONG_KEYWORDS)
    fe_hard = any(sig in blob for sig in FRONTEND_HARD_SIGNALS)
    fe_soft = score_hits(blob, FRONTEND_SOFT_KEYWORDS)
    be = score_hits(blob, BACKEND_STRONG_KEYWORDS)
    fe_strong = fe_hard or (has_fullstack and fe_soft >= 2) or (fe_soft >= 4)
    if fe_strong and be <= 1:
        return True, f"frontend_strong fe_hard={fe_hard} fe_soft={fe_soft} fullstack={has_fullstack} be={be}"
    return False, f"not_frontend fe_hard={fe_hard} fe_soft={fe_soft} fullstack={has_fullstack} be={be}"


def requires_us_person_or_citizen(text: str):
    t = (text or "").lower()
    triggers = [
        "u.s. person", "us person required",
        "u.s. citizen", "us citizen", "us citizen only", "must be a u.s. citizen",
        "security clearance", "top secret", "ts/sci", "secret clearance",
        "itar", "export control"
    ]
    for s in triggers:
        if s in t:
            return True, s
    return False, "ok"


def should_apply(title: str, card_text: str, role_context: str):
    bay = is_bay_area_from_text((card_text or "") + " " + (role_context or ""))
    fe_fs, fe_reason = frontend_diagnose(title, role_context)
    if (not bay) and fe_fs:
        return False, f"skip non_bay + {fe_reason}"
    return True, f"apply bay={bay} {fe_reason}"


# ============================================================
# Editability fallback
# ============================================================
def interest_field_editable(page):
    try:
        ta = page.locator("textarea#interest-blub")
        if ta.count() > 0:
            el = ta.first
            if not el.is_visible():
                return False, "interest_blub_not_visible"
            if not el.is_enabled():
                return False, "interest_blub_disabled"
            ro = el.get_attribute("readonly")
            if ro is not None:
                return False, "interest_blub_readonly"
            return True, "ok"

        any_ta = page.locator("textarea")
        for i in range(min(any_ta.count(), 6)):
            el = any_ta.nth(i)
            try:
                if el.is_visible() and el.is_enabled() and el.get_attribute("readonly") is None:
                    return True, "ok_fallback_textarea"
            except Exception:
                continue

        return False, "no_editable_textarea"
    except Exception as e:
        return False, f"interest_editable_check_error:{e}"


# ============================================================
# Scoring
# ============================================================
def compute_score(title: str, card_text: str, role_context: str) -> int:
    blob = " ".join([title or "", card_text or "", role_context or ""]).lower()
    pos = score_hits(blob, SCORE_KEYWORDS)
    neg = score_hits(blob, NEGATIVE_SCORE_KEYWORDS)
    be = score_hits(blob, BACKEND_STRONG_KEYWORDS)
    score = pos + (1 if be >= 6 else 0) - neg
    return max(score, 0)


# ============================================================
# OpenAI via Responses API (urllib) + retry
# ============================================================
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def openai_text(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in env.")

    org_id = os.environ.get("OPENAI_ORG_ID")
    project_id = os.environ.get("OPENAI_PROJECT_ID")

    payload = {
        "model": MODEL,
        "input": [
            {"role": "system", "content": "You write natural, specific internal transfer application answers. One paragraph. No bullet points. No hype."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_output_tokens": 260,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if org_id:
        headers["OpenAI-Organization"] = org_id
    if project_id:
        headers["OpenAI-Project"] = project_id

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", "6"))
    base_sleep = float(os.environ.get("OPENAI_RETRY_BASE_SLEEP", "0.8"))

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")

            data = json.loads(body)
            out = []
            for item in data.get("output", []):
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        out.append(c.get("text", ""))
            text = " ".join(out).strip()
            return re.sub(r"\s+", " ", text).strip()

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            last_err = RuntimeError(
                f"OpenAI API HTTPError {e.code}: {e.reason}\n{err_body}")

            if e.code not in RETRYABLE_HTTP:
                raise last_err from e

            if attempt < max_retries:
                sleep_s = base_sleep * (2 ** attempt) + random.uniform(0, 0.25)
                print(
                    f"[{ts()}] OpenAI HTTP {e.code} retrying in {sleep_s:.2f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(sleep_s)
                continue

            raise last_err from e

        except urllib.error.URLError as e:
            last_err = RuntimeError(f"OpenAI API URLError: {e}")
            if attempt < max_retries:
                sleep_s = base_sleep * (2 ** attempt) + random.uniform(0, 0.25)
                print(
                    f"[{ts()}] OpenAI URLError retrying in {sleep_s:.2f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(sleep_s)
                continue
            raise last_err from e

    raise last_err or RuntimeError("OpenAI API call failed (unknown)")


# ============================================================
# Prompting
# ============================================================
BAD_STYLE_HINTS = [
    "fast paced", "innovative", "cutting edge", "synergy",
    "passionate about", "aligns well", "i am drawn to", "scalable solutions"
]


def looks_templated(text: str) -> bool:
    tl = (text or "").lower()
    if not text:
        return True
    if any(p in tl for p in BAD_STYLE_HINTS):
        return True
    if len(text) < 380:
        return True
    return False


def extract_role_signals(role_context: str, max_signals: int = 10) -> list[str]:
    t = (role_context or "").lower()
    candidates = [
        "distributed systems", "services", "microservices", "api", "pipeline", "etl",
        "streaming", "kafka", "spark", "flink", "database", "storage", "sql", "query",
        "reliability", "availability", "latency", "performance", "observability",
        "monitoring", "metrics", "logging", "tracing", "oncall", "incident",
        "security", "privacy", "compliance", "payments", "billing", "pricing", "fraud",
        "machine learning", "inference", "training", "genai", "llm",
        "aws", "s3", "dynamodb", "eks", "ecs", "lambda"
    ]
    found = []
    for kw in candidates:
        if kw in t:
            found.append(kw)
        if len(found) >= max_signals:
            break
    return found


GOOD_EXAMPLE = """
I’m interested in this role because it sits at the intersection of distributed systems, query execution, and infrastructure reliability, which are the areas I enjoy building in and have shipped production work for. In AWS Redshift Storage, I focused on data management workflows and system level validation: I built a sliding window anomaly detector that enabled real time SEV creation and reduced response time from two months to one week, and I improved a Jenkins to Hydra migration tool that raised conversion from 20 percent to 90 percent. I also built Swarm system and performance tests for Vacuum workflows, designed sortedness effectiveness metrics for AutoVacuum Sort and Recluster, and optimized block overlap detection from N squared to N log N on 10TB tables. I work daily in C plus plus and Python, and I use AI assisted tooling to accelerate iteration while keeping review quality high. I’d love to chat about how I can apply this same reliability and performance discipline to the team’s analytics engine and query platform.
""".strip()


def gen_interest_answer(title: str, role_context: str) -> str:
    signals = extract_role_signals(role_context)
    signals_str = ", ".join(
        signals[:10]) if signals else "reliability, scale, correctness"

    prompt = f"""
You write short internal transfer application answers.

Constraints:
- One paragraph only
- 120 to 170 words
- Natural, confident tone. No apology. No hype words.
- No bullet points.
- You may ONLY reference facts that appear in the role context excerpt or the candidate background.
- Do not invent system names, metrics, or customer details not present.
- Make the candidate achievements explicitly map to the role needs.
- Avoid copying phrasing from the good example. Do not reuse exact sentences.

GOOD EXAMPLE (style to imitate, do not copy verbatim):
{GOOD_EXAMPLE}

Now write a NEW answer for this role.

Structure:
- Sentence 1: why the role matters + why I care (use role excerpt)
- Sentences 2 to 4: 2 to 3 concrete achievements mapped to role needs (use numbers)
- Final sentence: what I will focus on in first 30 to 60 days using these signals: {signals_str}

Role title: {title}

Role context excerpt:
{role_context[:2200]}

Candidate background:
{CANDIDATE_PROFILE}
""".strip()

    return openai_text(prompt)


def gen_interest_answer_with_retry(title: str, role_context: str) -> str:
    first = gen_interest_answer(title, role_context)
    if not looks_templated(first):
        return first

    prompt = f"""
Rewrite the answer to be more specific and human.
One paragraph, 120 to 170 words.
Use at least two numbers from my background.
Do not use hype words like "innovative", "fast paced", "cutting edge".
Do not copy the good example.

Role title: {title}

Role context excerpt:
{role_context[:2200]}

Candidate background:
{CANDIDATE_PROFILE}

Draft:
{first}
""".strip()
    return openai_text(prompt)


# ============================================================
# AboutMe fill + submit
# ============================================================
def aboutme_url(job_id: str) -> str:
    return f"{ABOUTME_ORIGIN}/{job_id}?ITW_LOCALE=en-US"


def review_url(job_id: str) -> str:
    return f"{ABOUTME_ORIGIN}/{job_id}/review"


def robust_fill_interest(page, text: str):
    ta = page.locator("textarea#interest-blub").first
    ta.wait_for(timeout=60000)

    ta.click()
    ta.fill("", timeout=30000)
    page.wait_for_timeout(100)

    ta.type(text, delay=TYPE_DELAY_MS)
    page.wait_for_timeout(150)

    page.evaluate(
        """
        (val) => {
          const el = document.querySelector("textarea#interest-blub");
          if (!el) return false;
          el.value = val;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        }
        """,
        text
    )

    current = ta.input_value(timeout=30000)
    return len(current or ""), current


# ============================================================
# ✅ Paging helpers (SIMPLE + ROBUST)
# ============================================================
def click_next_page_simple(page, timeout_ms: int = 20000) -> bool:
    """
    Improved next-page click with multiple fallback strategies
    """
    # Wait for pagination to be ready
    try:
        page.wait_for_selector(
            "#search-navigation-sidebar-section", timeout=60000)
        page.wait_for_timeout(500)  # Let any animations settle
    except Exception as e:
        print(f"[{ts()}] [paging] sidebar not found: {e}")
        return False

    # Find the next button - try multiple selectors
    next_btn = None
    selectors = [
        "button[data-test-id='next-page']:not([aria-disabled='true']):not([disabled])",
        "button[data-test-id='next-page']",
        "//button[contains(text(), 'Next page')]",
    ]

    for selector in selectors:
        try:
            if selector.startswith("//"):
                candidates = page.locator(f"xpath={selector}")
            else:
                candidates = page.locator(selector)

            if candidates.count() > 0:
                # Find visible one
                for i in range(candidates.count()):
                    cand = candidates.nth(i)
                    try:
                        if cand.is_visible():
                            next_btn = cand
                            break
                    except Exception:
                        continue
                if next_btn:
                    break
        except Exception:
            continue

    if not next_btn:
        print(f"[{ts()}] [paging] next-page button not found with any selector")
        return False

    # Check if disabled
    try:
        aria_disabled = next_btn.get_attribute("aria-disabled")
        if aria_disabled == "true":
            print(f"[{ts()}] [paging] next-page is aria-disabled (last page)")
            return False

        if next_btn.get_attribute("disabled") is not None:
            print(f"[{ts()}] [paging] next-page is disabled (last page)")
            return False
    except Exception as e:
        print(f"[{ts()}] [paging] Could not check disabled state: {e}")

    # Capture current state - use multiple signals
    try:
        # Get the current URL (might have ?page=2 etc)
        before_url = page.url

        # Get first card ID as backup signal
        first_card = page.locator(
            "#search-navigation-sidebar-section div[id^='role-card-']"
        ).first
        before_id = first_card.get_attribute(
            "id") if first_card.count() > 0 else None

        # Get page number from DOM
        page_indicator = page.locator(
            "[aria-live='polite'][role='status']").first
        before_page_text = page_indicator.inner_text() if page_indicator.count() > 0 else ""

    except Exception as e:
        print(f"[{ts()}] [paging] Could not capture before-state: {e}")
        before_url = None
        before_id = None
        before_page_text = ""

    # Click the button
    try:
        next_btn.scroll_into_view_if_needed(timeout=10000)
        page.wait_for_timeout(300)
        next_btn.click(timeout=8000)
        print(f"[{ts()}] [paging] Clicked next-page button")
    except Exception as e:
        print(f"[{ts()}] [paging] Failed to click next button: {e}")
        return False

    # Wait for change using multiple signals
    deadline = time.time() + (timeout_ms / 1000.0)
    change_detected = False

    while time.time() < deadline:
        try:
            # Check URL change
            now_url = page.url
            if before_url and now_url != before_url:
                print(f"[{ts()}] [paging] URL changed: {before_url} -> {now_url}")
                change_detected = True
                break

            # Check page indicator text change
            page_indicator = page.locator(
                "[aria-live='polite'][role='status']").first
            if page_indicator.count() > 0:
                now_page_text = page_indicator.inner_text()
                if before_page_text and now_page_text != before_page_text:
                    print(
                        f"[{ts()}] [paging] Page indicator changed: '{before_page_text}' -> '{now_page_text}'")
                    change_detected = True
                    break

            # Check first card ID change (fallback)
            first_card = page.locator(
                "#search-navigation-sidebar-section div[id^='role-card-']"
            ).first
            if first_card.count() > 0:
                now_id = first_card.get_attribute("id")
                if before_id and now_id and now_id != before_id:
                    print(
                        f"[{ts()}] [paging] First card ID changed: {before_id} -> {now_id}")
                    change_detected = True
                    break

        except Exception:
            pass

        page.wait_for_timeout(200)

    if change_detected:
        # Give it a moment to fully render
        page.wait_for_timeout(600)
        return True
    else:
        print(f"[{ts()}] [paging] Clicked next but no change detected (timeout)")
        return False


def has_next_page(page) -> bool:
    """Return True if Next button is enabled (not aria-disabled/disabled)."""
    try:
        # Wait a moment for pagination to stabilize
        page.wait_for_timeout(500)

        all_next = page.locator("button[data-test-id='next-page']")
        count = all_next.count()
        print(f"[{ts()}] [has_next_page] Found {count} next-page buttons")

        if count == 0:
            print(
                f"[{ts()}] [has_next_page] No buttons found - trying fallback selector")
            # Fallback: try finding by text
            all_next = page.locator("button:has-text('Next page')")
            count = all_next.count()
            print(f"[{ts()}] [has_next_page] Fallback found {count} buttons")
            if count == 0:
                return False

        # Find visible button
        next_btn = None
        for i in range(all_next.count()):
            cand = all_next.nth(i)
            try:
                if cand.is_visible():
                    next_btn = cand
                    print(f"[{ts()}] [has_next_page] Using visible button #{i}")
                    break
            except Exception:
                continue

        if not next_btn:
            next_btn = all_next.first
            print(f"[{ts()}] [has_next_page] No visible button, using first")

        # Check disabled state
        aria_disabled = next_btn.get_attribute("aria-disabled")
        disabled_attr = next_btn.get_attribute("disabled")

        print(
            f"[{ts()}] [has_next_page] aria-disabled='{aria_disabled}' disabled='{disabled_attr}'")

        if aria_disabled == "true":
            print(
                f"[{ts()}] [has_next_page] Button is aria-disabled=true → LAST PAGE")
            return False

        if disabled_attr is not None:
            print(
                f"[{ts()}] [has_next_page] Button has disabled attribute → LAST PAGE")
            return False

        print(f"[{ts()}] [has_next_page] Button is ENABLED → has next page")
        return True

    except Exception as e:
        print(f"[{ts()}] [has_next_page] Exception: {e}")
        traceback.print_exc()
        return False

# ============================================================
# Left panel helpers
# ============================================================


def get_cards(page):
    page.wait_for_selector("#search-navigation-sidebar-section", timeout=60000)
    sidebar = page.locator("#search-navigation-sidebar-section").first
    cards = sidebar.locator("div[id^='role-card-']")
    return sidebar, cards, cards.count()


# ============================================================
# High score handlers
# ============================================================
def format_role_line(job_id: str, title: str, score: int) -> str:
    return f"Job ID {job_id} | score={score} | {title}\nAboutMe: {aboutme_url(job_id)}\nReview:  {review_url(job_id)}\n"


def interactive_high_score_flow(page, job_id: str, title: str, score: int, out_dir: str, role_context: str):
    print(f"[{ts()}] HIGH SCORE interactive stop: job_id={job_id} score={score} title={title}")

    ok_edit, edit_reason = interest_field_editable(page)
    if not ok_edit:
        print(
            f"[{ts()}] High score but cannot edit interest field: {edit_reason}. Skipping apply flow.")
        try:
            page.screenshot(path=os.path.join(
                out_dir, f"highscore_not_editable_{job_id}.png"), full_page=True)
        except Exception:
            pass
        input("High score role not editable. Press Enter to continue...")
        return

    why = gen_interest_answer_with_retry(title, role_context)
    print(f"[{ts()}] Generated interest answer:")
    print(why)
    print("")

    filled_len, _ = robust_fill_interest(page, why)
    print(f"[{ts()}] Filled interest-blub length={filled_len}")

    try:
        page.screenshot(path=os.path.join(
            out_dir, f"highscore_filled_{job_id}.png"), full_page=True)
    except Exception:
        pass

    page.goto(review_url(job_id), wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    try:
        page.screenshot(path=os.path.join(
            out_dir, f"highscore_review_{job_id}.png"), full_page=True)
    except Exception:
        pass

    choice = input(
        "High score role ready. Submit manually in browser, then type Enter to continue. (s=skip, q=quit): ").strip().lower()
    if choice == "q":
        raise SystemExit("User quit.")


# ============================================================
# Main
# ============================================================
def run():
    out_dir = os.path.join(
        "outputs", f"auto_submit_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"[{ts()}] MODE={MODE} AUTO_SUBMIT={AUTO_SUBMIT}")
    print(f"[{ts()}] Output: {out_dir}")
    print(f"[{ts()}] can_email={can_email()} SMTP_USER={'set' if SMTP_USER else 'EMPTY'} SMTP_PASS={'set' if SMTP_PASS else 'EMPTY'} EMAIL_TO={EMAIL_TO}")
    print(f"[{ts()}] HIGH_SCORE_THRESHOLD={HIGH_SCORE_THRESHOLD} MODE={MODE}")

    applied = 0
    skipped = 0
    processed = 0

    high_score_hits = []
    apply_now_jobs = []

    gmail_service = None
    if ENABLE_GMAIL_OTP:
        try:
            gmail_service = get_gmail_service()
            print(f"[{ts()}] Gmail service ready (OTP automation enabled).")
        except Exception as e:
            print(f"[{ts()}] Gmail service init failed: {e}")
            gmail_service = None

    with sync_playwright() as p:
        PROFILE_DIR = os.environ.get("PROFILE_DIR", "")
        profile_dir = PROFILE_DIR if PROFILE_DIR else (
            "./chrome_profile_auto" if MODE == "auto" else "./chrome_profile")

        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False
        )
        page = ctx.new_page()

        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        if not handle_login(page, out_dir, gmail_service=gmail_service):
            print(f"[{ts()}] Exiting due to login.")
            ctx.close()
            return

        page_index = 1
        while True:
            ensure_on_search_page(page)
            sidebar, cards, total = get_cards(page)

            # record current paged URL (keeps page=2,3,... if present)
            search_page_url = page.url
            print(
                f"\n[{ts()}] Page {page_index} cards: {total} url={search_page_url}")

            for k in range(total):
                try:
                    # always return to the exact paged URL for this page
                    if page.url != search_page_url:
                        try:
                            page.goto(search_page_url,
                                      wait_until="domcontentloaded")
                            page.wait_for_timeout(600)
                        except Exception:
                            pass

                    sidebar, cards, total2 = get_cards(page)
                    if k >= total2:
                        break

                    processed += 1

                    card = cards.nth(k)
                    card.scroll_into_view_if_needed(timeout=10000)

                    meta_raw = card.inner_text(timeout=15000)
                    meta_lines = [ln.strip()
                                  for ln in meta_raw.splitlines() if ln.strip()]
                    title = meta_lines[0] if meta_lines else f"title_{page_index}_{k}"
                    card_text = clean(meta_raw)

                    if SKIP_INTERNSHIP and re.search(r"\bintern\b|\binternship\b", (title or "").lower()):
                        print(
                            f"[{ts()}] Tile p{page_index}#{k}: {title} -> skip internship")
                        skipped += 1
                        continue

                    print(f"\n[{ts()}] Tile p{page_index}#{k}: {title}")
                    card.click()
                    page.wait_for_timeout(450)

                    right = find_right_panel_container(page)
                    job_id, _preview = wait_job_id_in_right_panel(
                        page, right, timeout_ms=30000)

                    if not job_id:
                        print(f"[{ts()}] WARN: no job id parsed, skipping")
                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"no_jobid_p{page_index}_{k}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    action = decide_role_action(right)
                    print(f"[{ts()}] job_id={job_id} action={action}")

                    if action == "APPLY_NOW":
                        role_context = ""
                        score = compute_score(title, card_text, "")

                        if ENRICH_APPLY_NOW:
                            try:
                                page.goto(aboutme_url(job_id),
                                          wait_until="domcontentloaded")
                                page.wait_for_timeout(900)
                                body_text = page.text_content("body") or ""
                                role_context = extract_jd_like_text(body_text)
                                score = compute_score(
                                    title, card_text, role_context)
                            except Exception:
                                role_context = ""

                        apply_now_jobs.append({
                            "job_id": job_id,
                            "title": title,
                            "score": score,
                            "search_url": search_page_url,
                            "aboutme_url": aboutme_url(job_id),
                            "review_url": review_url(job_id),
                            "seen_at": datetime.now().isoformat(timespec="seconds"),
                            "page_index": page_index,
                            "card_index": k,
                            "card_text_preview": card_text[:FILTER_DEBUG_PREVIEW_CHARS],
                            "role_context_preview": (role_context[:FILTER_DEBUG_PREVIEW_CHARS] if role_context else ""),
                        })

                        print(
                            f"[{ts()}] APPLY NOW captured: {job_id} | score={score} | {title}")
                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"apply_now_{job_id}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    if action == "SKIP":
                        print(
                            f"[{ts()}] No Request informational and no Apply now. Skip.")
                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"skipped_no_action_{job_id}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    # INFO flow
                    page.goto(aboutme_url(job_id),
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(900)

                    body_text = page.text_content("body") or ""
                    role_context = extract_jd_like_text(body_text)

                    cit_skip, cit_reason = requires_us_person_or_citizen(
                        body_text)
                    if cit_skip:
                        print(
                            f"[{ts()}] decision=skip requires_us_person_or_citizen hit={cit_reason}")
                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"skipped_usperson_{job_id}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    do_apply, reason = should_apply(
                        title, card_text, role_context)
                    print(f"[{ts()}] decision={reason}")
                    if not do_apply:
                        if DEBUG_FILTERING:
                            print(f"[{ts()}] SKIP DEBUG title={title}")
                            print(
                                f"[{ts()}] card_text_preview={card_text[:FILTER_DEBUG_PREVIEW_CHARS]}")
                            print(
                                f"[{ts()}] role_ctx_preview={role_context[:FILTER_DEBUG_PREVIEW_CHARS]}")
                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"skipped_policy_{job_id}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    score = compute_score(title, card_text, role_context)
                    if score >= HIGH_SCORE_THRESHOLD:
                        line = format_role_line(job_id, title, score)
                        high_score_hits.append(line)
                        print(
                            f"[{ts()}] HIGH SCORE detected (score={score} >= {HIGH_SCORE_THRESHOLD})")
                        print(line)

                        if MODE == "interactive":
                            interactive_high_score_flow(
                                page, job_id, title, score, out_dir, role_context)
                        else:
                            try:
                                page.screenshot(path=os.path.join(
                                    out_dir, f"highscore_{job_id}_{ts().replace(':','')}.png"), full_page=True)
                            except Exception:
                                pass

                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"highscore_back_{job_id}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    ok_edit, edit_reason = interest_field_editable(page)
                    if not ok_edit:
                        print(
                            f"[{ts()}] decision=skip interest_field_not_editable reason={edit_reason}")
                        skipped += 1
                        post_return_to_search(
                            page, out_dir, f"skipped_not_editable_{job_id}_{ts().replace(':','')}.png", search_page_url)
                        continue

                    why = gen_interest_answer_with_retry(title, role_context)
                    print(f"[{ts()}] Generated interest answer:")
                    print(why)
                    print("")

                    filled_len, _ = robust_fill_interest(page, why)
                    print(f"[{ts()}] Filled interest-blub length={filled_len}")
                    try:
                        page.screenshot(path=os.path.join(
                            out_dir, f"filled_{job_id}_{ts().replace(':','')}.png"), full_page=True)
                    except Exception:
                        pass

                    page.goto(review_url(job_id),
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(900)

                    submit_btn = page.get_by_role(
                        "button", name="Submit").first
                    submit_btn.wait_for(timeout=60000)
                    submit_btn.scroll_into_view_if_needed(timeout=10000)

                    try:
                        page.screenshot(path=os.path.join(
                            out_dir, f"review_{job_id}_{ts().replace(':','')}.png"), full_page=True)
                    except Exception:
                        pass

                    if AUTO_SUBMIT:
                        submit_btn.click()
                        page.wait_for_timeout(1500)
                        try:
                            page.screenshot(path=os.path.join(
                                out_dir, f"submitted_{job_id}_{ts().replace(':','')}.png"), full_page=True)
                        except Exception:
                            pass
                        print(f"[{ts()}] Submitted job_id={job_id}")
                        applied += 1
                    else:
                        input(
                            "On review page. Submit manually in browser, then press Enter to continue...")

                    post_return_to_search(
                        page, out_dir, f"after_submit_{job_id}_{ts().replace(':','')}.png", search_page_url)

                except SystemExit as e:
                    print(f"[{ts()}] {e}")
                    raise
                except Exception as e:
                    print(f"[{ts()}] EXCEPTION on tile p{page_index}#{k}: {e}")
                    traceback.print_exc()
                    skipped += 1
                    post_return_to_search(
                        page, out_dir, f"exception_p{page_index}_{k}_{ts().replace(':','')}.png", search_page_url)
                    continue

            # --- ✅ Move to next page (SIMPLE) ---
            # --- ✅ Move to next page ---
            print(
                f"\n[{ts()}] Page {page_index} complete ({processed} processed total). Checking for next page...")

            # CRITICAL: Ensure we're on the search page and it's fully loaded
            try:
                if page.url != search_page_url:
                    print(
                        f"[{ts()}] [paging] Not on search page, navigating back...")
                    page.goto(search_page_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1200)
            except Exception as e:
                print(f"[{ts()}] [paging] Error returning to search: {e}")

            # Wait for sidebar to be fully loaded
            try:
                page.wait_for_selector(
                    "#search-navigation-sidebar-section", timeout=30000)
                # Extra settle time for pagination buttons
                page.wait_for_timeout(800)
            except Exception as e:
                print(f"[{ts()}] [paging] Sidebar not ready: {e}")
                break

            # Take diagnostic screenshot
            try:
                page.screenshot(path=os.path.join(
                    out_dir, f"before_next_page{page_index}.png"), full_page=True)
            except Exception:
                pass

            # Diagnostic: Check page state
            try:
                indicator = page.locator(
                    "[aria-live='polite'][role='status']").first
                if indicator.count() > 0:
                    text = indicator.inner_text()
                    print(f"[{ts()}] [paging] Page indicator: '{text}'")

                cards_now = page.locator(
                    "#search-navigation-sidebar-section div[id^='role-card-']").count()
                print(f"[{ts()}] [paging] Visible cards on page: {cards_now}")
            except Exception:
                pass

            # Check pagination state
            print(f"[{ts()}] [paging] before_next url={page.url}")

            has_next = has_next_page(page)
            print(f"[{ts()}] [paging] has_next_page returned: {has_next}")

            if not has_next:
                print(f"[{ts()}] [paging] No next page detected. Stopping.")
                break

            # Attempt to move to next page
            moved = click_next_page_simple(page)
            print(f"[{ts()}] [paging] after_next moved={moved} url={page.url}")

            if not moved:
                print(f"[{ts()}] [paging] Failed to move to next page. Stopping.")
                break

            page_index += 1

            # Extra wait for new page to settle
            page.wait_for_timeout(1500)

        print(f"\n[{ts()}] Done. Logs in: {out_dir}")
        print(f"[{ts()}] applied={applied} skipped={skipped} processed={processed}")
        print(
            f"[{ts()}] high_score_hits={len(high_score_hits)} apply_now_jobs={len(apply_now_jobs)}")

        if apply_now_jobs:
            path = os.path.join(out_dir, "apply_now_jobs.json")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(apply_now_jobs, f, indent=2, ensure_ascii=False)
                print(
                    f"[{ts()}] Wrote apply-now jobs: {path} (count={len(apply_now_jobs)})")
            except Exception as e:
                print(f"[{ts()}] Failed to write apply_now_jobs.json: {e}")

        if high_score_hits:
            subject = f"[BUZOU] High score roles found ({len(high_score_hits)})"
            body = (
                "High score roles (not auto applied):\n\n"
                + "\n\n".join(high_score_hits)
                + f"\n\nLogs: {out_dir}\nTime: {datetime.now()}\n"
            )
            if MODE == "interactive":
                choice = input(
                    "Send high score summary email? (y/N): ").strip().lower()
                if choice == "y":
                    send_email(subject, body)
            else:
                send_email(subject, body)

        if MODE == "interactive":
            input("Browser kept open. Press Enter to close...")

        ctx.close()


if __name__ == "__main__":
    run()
