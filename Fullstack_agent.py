from playwright.sync_api import sync_playwright
import re
import json
from datetime import datetime
import os
import traceback
import urllib.request
import urllib.error
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse

# ----------------------------
# Config
# ----------------------------
MODE = os.environ.get("MODE", "interactive").lower().strip()
# MODE = "auto" or "interactive"

TYPE_DELAY_MS = int(os.environ.get("TYPE_DELAY_MS", "10"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# In auto mode we never block on input and we auto submit non high score jobs
AUTO_SUBMIT = (MODE == "auto")

ABOUTME_ORIGIN = "https://prod.aboutme.talent.amazon.dev"

# Skip internships by default (recommended to avoid signal pollution)
SKIP_INTERNSHIP = True

# Debug filtering decisions
DEBUG_FILTERING = True
FILTER_DEBUG_PREVIEW_CHARS = 280

# Email settings (for high score notifications / login failures)
EMAIL_TO = os.environ.get("EMAIL_TO", "laiyanting.neu@gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM", os.environ.get("SMTP_USER", ""))  # usually same as SMTP_USER
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# Scoring thresholds
HIGH_SCORE_THRESHOLD = int(os.environ.get("HIGH_SCORE_THRESHOLD", "8"))

# ----------------------------
# Candidate profile (stable, always injected)
# ----------------------------
CANDIDATE_PROFILE = """
I am a software engineer on AWS Redshift Vacuum and storage data plane.
I designed a sliding window anomaly detector for vacuum transactions and enabled real time SEV creation, reducing response time from 2 months to 1 week.
I improved the Jenkins to Hydra test migration tool, raising conversion rate from 20% to 90%.
I built swarm system tests and performance tests for Vacuum workflows and found critical bugs before release.
I designed sortedness effectiveness metrics for AutoVacuum Sort and Recluster and optimized block overlap detection from N^2 to N log N on 10TB tables.
My next step is AI infrastructure and platform engineering: scalable systems, data and model pipelines, reliability, performance, and observability.
""".strip()

# ----------------------------
# Your policy:
# If NOT Bay Area and clearly frontend/fullstack => skip
# Otherwise apply
# ----------------------------
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

# Keywords used for scoring “interesting” roles (simple heuristic, tunable)
SCORE_KEYWORDS = [
    # infra / platform
    "platform", "infrastructure", "distributed", "systems", "scalability",
    "reliability", "availability", "latency", "throughput", "observability",
    "metrics", "tracing", "logging", "oncall", "incident", "performance",
    # data / pipelines
    "data", "pipeline", "etl", "streaming", "kafka", "spark", "flink",
    "database", "storage", "sql", "query", "index", "cache",
    # ML / AI (only scoring, not writing prompt unless title says ML/AI)
    "ml", "machine learning", "model", "inference", "training", "llm", "genai",
    # AWS signals
    "aws", "s3", "dynamodb", "ecs", "eks", "ec2", "lambda", "sagemaker"
]

NEGATIVE_SCORE_KEYWORDS = [
    "react", "angular", "vue", "css", "html", "mobile", "ios", "android",
    "design system", "component library", "ux", "ui"
]

# ----------------------------
# URL config
# ----------------------------
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()

def origin_from_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

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

# ----------------------------
# Email helper
# ----------------------------
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

# ----------------------------
# Login detection + handler
# ----------------------------
def is_logged_in_search_page(page) -> bool:
    """
    Heuristic: if we can see the sidebar section OR role cards, we assume logged in.
    Also guard against obvious login/auth URLs.
    """
    u = (page.url or "").lower()
    if "login" in u or "signin" in u or "auth" in u:
        return False
    try:
        if page.locator("#search-navigation-sidebar-section").count() > 0:
            return True
        if page.locator("div[id^='role-card-']").count() > 0:
            return True
    except Exception:
        pass
    return False

def handle_login(page, out_dir: str) -> bool:
    """
    Returns True if logged in and we can proceed.

    New behavior you requested:
    - auto mode: if not logged in, WAIT for manual login in the opened browser
      instead of emailing + aborting.

    Optional env:
    - AUTO_LOGIN_TIMEOUT_SEC: 0 = wait forever; otherwise abort after N seconds.
    - AUTO_LOGIN_EMAIL_ON_TIMEOUT: "1" to email only on timeout.
    """
    if is_logged_in_search_page(page):
        print(f"[{ts()}] Already logged in (session context).")
        return True

    print(f"[{ts()}] Not logged in on search page.")
    try:
        page.screenshot(path=os.path.join(out_dir, "not_logged_in.png"), full_page=True)
    except Exception:
        pass

    # Always navigate to SEARCH_URL for a stable login entry
    try:
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
    except Exception:
        pass

    if MODE == "auto":
        timeout_sec = int(os.environ.get("AUTO_LOGIN_TIMEOUT_SEC", "0"))  # 0 = wait forever
        email_on_timeout = os.environ.get("AUTO_LOGIN_EMAIL_ON_TIMEOUT", "0") == "1"

        msg = f"[{ts()}] AUTO mode needs login. Please finish AEA/login in the opened browser."
        if timeout_sec > 0:
            msg += f" Timeout {timeout_sec}s."
        print(msg)

        start = datetime.now().timestamp()
        while True:
            # Re-check: after login, we should be able to load search and see role cards
            try:
                page.goto(SEARCH_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
            except Exception:
                pass

            if is_logged_in_search_page(page):
                print(f"[{ts()}] Login detected. Continue auto run.")
                return True

            if timeout_sec > 0 and (datetime.now().timestamp() - start) > timeout_sec:
                print(f"[{ts()}] AUTO login timeout reached. Aborting run.")
                if email_on_timeout:
                    send_email(
                        subject="[BUZOU] Login required (auto run timed out)",
                        body=f"Auto run waited for login but timed out.\nTime: {datetime.now()}\nLogs: {out_dir}\n"
                    )
                return False

            page.wait_for_timeout(1000)

    # interactive mode (original behavior)
    input("Finish login/AEA in the opened browser, then press Enter here...")
    page.goto(SEARCH_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    ok = is_logged_in_search_page(page)
    print(f"[{ts()}] Login status after manual step: {ok}")
    return ok

# ----------------------------
# Right panel helpers
# ----------------------------
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
            last_preview = clean(right_container.inner_text(timeout=1500) or "")
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

# ----------------------------
# Extract JD-like text (for filtering)
# ----------------------------
JD_KEEP_KEYWORDS = [
    "build", "design", "own", "deliver", "develop", "maintain", "operate", "scale",
    "improve", "optimize", "monitor", "measure", "debug", "deploy",
    "distributed", "reliability", "availability", "latency", "performance",
    "observability", "monitoring", "metrics", "logging", "tracing", "incident",
    "data integrity", "data quality", "pipeline", "platform", "infrastructure",
    "machine learning", "model", "training", "inference", "feature", "ranking",
    "fraud", "trust", "integrity", "anomaly", "detection",
    "aws", "s3", "dynamodb", "kafka", "spark", "airflow", "python", "java", "c++",
    "sql", "etl"
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

# ----------------------------
# Role filtering logic
# ----------------------------
def is_bay_area_from_text(text: str) -> bool:
    tl = (text or "").lower()
    return any(h in tl for h in BAY_AREA_HINTS)

def score_hits(blob: str, keywords: list[str]) -> int:
    blob = (blob or "").lower()
    return sum(1 for kw in keywords if kw in blob)

def frontend_diagnose(title: str, role_context: str) -> (bool, str):
    blob = " ".join([title or "", role_context or ""]).lower()

    has_fullstack = any(kw in blob for kw in FULLSTACK_STRONG_KEYWORDS)
    fe_hard = any(sig in blob for sig in FRONTEND_HARD_SIGNALS)
    fe_soft = score_hits(blob, FRONTEND_SOFT_KEYWORDS)
    be = score_hits(blob, BACKEND_STRONG_KEYWORDS)

    fe_strong = fe_hard or (has_fullstack and fe_soft >= 2) or (fe_soft >= 4)

    if fe_strong and be <= 1:
        return True, f"frontend_strong fe_hard={fe_hard} fe_soft={fe_soft} fullstack={has_fullstack} be={be}"

    return False, f"not_frontend fe_hard={fe_hard} fe_soft={fe_soft} fullstack={has_fullstack} be={be}"

def requires_us_person_or_citizen(text: str) -> (bool, str):
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

def should_apply(title: str, card_text: str, role_context: str) -> (bool, str):
    bay = is_bay_area_from_text((card_text or "") + " " + (role_context or ""))
    fe_fs, fe_reason = frontend_diagnose(title, role_context)

    if (not bay) and fe_fs:
        return False, f"skip non_bay + {fe_reason}"

    return True, f"apply bay={bay} {fe_reason}"

# ----------------------------
# Editability fallback (skip roles like "Introduce yourself" not editable)
# ----------------------------
def interest_field_editable(page) -> (bool, str):
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

# ----------------------------
# Scoring high interest roles (simple heuristic)
# ----------------------------
def compute_score(title: str, card_text: str, role_context: str) -> int:
    blob = " ".join([title or "", card_text or "", role_context or ""]).lower()
    pos = score_hits(blob, SCORE_KEYWORDS)
    neg = score_hits(blob, NEGATIVE_SCORE_KEYWORDS)
    # small bonus for backend strong signals
    be = score_hits(blob, BACKEND_STRONG_KEYWORDS)
    score = pos + (1 if be >= 6 else 0) - neg
    return max(score, 0)

# ----------------------------
# OpenAI (urllib)
# ----------------------------
def openai_chat(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in env.")

    org_id = os.environ.get("OPENAI_ORG_ID")
    project_id = os.environ.get("OPENAI_PROJECT_ID")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You write concise Amazon internal transfer answers. No hyphens."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "max_tokens": 280,
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
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"OpenAI API HTTPError {e.code}: {e.reason}\n{err_body}") from e

    data = json.loads(body)
    text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()

    # enforce "no hyphens"
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ----------------------------
# Prompting
# ----------------------------
BAD_PHRASES = [
    "i am drawn to", "aligns well", "crucial for", "opportunity to work on",
    "advance toward", "help me advance", "fast paced", "innovative",
    "enhance existing systems", "implement robust monitoring solutions",
    "scalable solutions"
]

def gen_why_interested(title: str) -> str:
    prompt = f"""
Write a Why interested answer for an Amazon internal transfer application.
110 to 160 words, 1 paragraph, natural human tone, no hyphens.

Structure:
1) 1 to 2 sentences: why this role matters in the real world (impact, customers, correctness, reliability, trust)
2) 2 to 3 sentences: my Redshift work with concrete facts and numbers
3) 1 sentence: what I will bring to this role (APIs/services, reliability/perf discipline, monitoring/alerting, collaboration)

Hard constraints:
Use ONLY information from Candidate background and the Role title. Do not invent role specific details.
Do not mention "AI infrastructure" unless the role title includes ML or AI.
Avoid generic filler. Do not use these phrases: {", ".join(BAD_PHRASES)}.

Role title: {title}

Candidate background:
{CANDIDATE_PROFILE}
""".strip()
    return openai_chat(prompt)

def quality_ok(text: str) -> bool:
    tl = (text or "").lower()
    if not text:
        return False
    if any(p in tl for p in BAD_PHRASES):
        return False
    if "\n" in text.strip():
        return False
    if len(re.findall(r"\d", text)) < 2:
        return False
    must_have = ["anomaly", "hydra", "vacuum", "sortedness", "overlap", "regression", "latency", "reliability"]
    hits = sum(1 for w in must_have if w in tl)
    return hits >= 2

def gen_why_interested_with_retry(title: str) -> str:
    first = gen_why_interested(title)
    if quality_ok(first):
        return first

    retry_prompt = f"""
Rewrite the answer below to follow the structure and constraints exactly.
Keep 110 to 160 words, 1 paragraph, no hyphens.
Make it specific, remove fluff, include at least two numbers from my background.
Do not invent role details.

Role title: {title}

Candidate background:
{CANDIDATE_PROFILE}

Bad draft:
{first}
""".strip()
    return openai_chat(retry_prompt)

# ----------------------------
# AboutMe fill + submit
# ----------------------------
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

# ----------------------------
# Paging helpers (search results)
# ----------------------------
def get_cards(page):
    page.wait_for_selector("#search-navigation-sidebar-section", timeout=60000)
    sidebar = page.locator("#search-navigation-sidebar-section").first
    cards = sidebar.locator("div[id^='role-card-']")
    return sidebar, cards, cards.count()

def click_next_page_if_possible(page) -> bool:
    candidates = []
    candidates.append(page.get_by_role("button", name=re.compile(r"Next", re.I)))
    candidates.append(page.get_by_role("link", name=re.compile(r"Next", re.I)))
    candidates.append(page.locator("button[aria-label*='Next' i]"))
    candidates.append(page.locator("a[aria-label*='Next' i]"))
    candidates.append(page.locator("nav[aria-label*='pagination' i] button:has-text('Next')"))
    candidates.append(page.locator("nav[aria-label*='pagination' i] a:has-text('Next')"))
    candidates.append(page.locator("button:has(svg[aria-label*='Next' i])"))
    candidates.append(page.locator("button:has-text('›')"))
    candidates.append(page.locator("button:has-text('→')"))

    for cand in candidates:
        try:
            if cand.count() <= 0:
                continue
            btn = cand.first
            disabled = btn.get_attribute("disabled")
            aria_disabled = btn.get_attribute("aria-disabled")
            if (disabled is not None) or (aria_disabled == "true"):
                continue
            btn.scroll_into_view_if_needed(timeout=10000)
            btn.click()
            page.wait_for_timeout(1200)
            page.wait_for_load_state("domcontentloaded")
            return True
        except Exception:
            continue
    return False

# ----------------------------
# High score handlers
# ----------------------------
def format_role_line(job_id: str, title: str, score: int) -> str:
    return f"Job ID {job_id} | score={score} | {title}\nAboutMe: {aboutme_url(job_id)}\nReview:  {review_url(job_id)}\n"

def interactive_high_score_flow(page, job_id: str, title: str, score: int, out_dir: str):
    print(f"[{ts()}] HIGH SCORE interactive stop: job_id={job_id} score={score} title={title}")

    ok_edit, edit_reason = interest_field_editable(page)
    if not ok_edit:
        print(f"[{ts()}] High score but cannot edit interest field: {edit_reason}. Skipping apply flow.")
        try:
            page.screenshot(path=os.path.join(out_dir, f"highscore_not_editable_{job_id}.png"), full_page=True)
        except Exception:
            pass
        input("High score role not editable. Press Enter to continue...")
        return

    why = gen_why_interested_with_retry(title)
    print(f"[{ts()}] Generated Why interested:")
    print(why)
    print("")

    filled_len, _ = robust_fill_interest(page, why)
    print(f"[{ts()}] Filled interest-blub length={filled_len}")

    try:
        page.screenshot(path=os.path.join(out_dir, f"highscore_filled_{job_id}.png"), full_page=True)
    except Exception:
        pass

    page.goto(review_url(job_id), wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    try:
        page.screenshot(path=os.path.join(out_dir, f"highscore_review_{job_id}.png"), full_page=True)
    except Exception:
        pass

    choice = input("High score role ready. Submit manually in browser, then type Enter to continue. (s=skip, q=quit): ").strip().lower()
    if choice == "q":
        raise SystemExit("User quit.")

# ----------------------------
# Main
# ----------------------------
def run():
    out_dir = os.path.join("outputs", f"auto_submit_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"[{ts()}] MODE={MODE} AUTO_SUBMIT={AUTO_SUBMIT}")
    print(f"[{ts()}] Output: {out_dir}")

    applied = 0
    skipped = 0
    processed = 0

    high_score_hits = []

    with sync_playwright() as p:

        PROFILE_DIR = os.environ.get("PROFILE_DIR", "")
        profile_dir = PROFILE_DIR if PROFILE_DIR else ("./chrome_profile_auto" if MODE == "auto" else "./chrome_profile")

        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False
        )
        page = ctx.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        if not handle_login(page, out_dir):
            print(f"[{ts()}] Exiting due to login.")
            ctx.close()
            return

        page_index = 1
        while True:
            sidebar, cards, total = get_cards(page)
            print(f"\n[{ts()}] Page {page_index} cards: {total}")

            for k in range(total):
                try:
                    sidebar, cards, total2 = get_cards(page)
                    if k >= total2:
                        break

                    card = cards.nth(k)
                    card.scroll_into_view_if_needed(timeout=10000)

                    meta_raw = card.inner_text(timeout=15000)
                    meta_lines = [ln.strip() for ln in meta_raw.splitlines() if ln.strip()]
                    title = meta_lines[0] if meta_lines else f"tile_{page_index}_{k}"
                    card_text = clean(meta_raw)

                    if SKIP_INTERNSHIP and re.search(r"\bintern\b|\binternship\b", (title or "").lower()):
                        print(f"[{ts()}] Tile p{page_index}#{k}: {title} -> skip internship")
                        skipped += 1
                        continue

                    print(f"\n[{ts()}] Tile p{page_index}#{k}: {title}")
                    card.click()
                    page.wait_for_timeout(450)

                    right = find_right_panel_container(page)
                    job_id, _preview = wait_job_id_in_right_panel(page, right, timeout_ms=30000)

                    if not job_id:
                        print(f"[{ts()}] WARN: no job id parsed, skipping")
                        try:
                            page.screenshot(path=os.path.join(out_dir, f"no_jobid_p{page_index}_{k}.png"), full_page=True)
                        except Exception:
                            pass
                        skipped += 1
                        continue

                    req_ok = has_request_informational(right)
                    print(f"[{ts()}] job_id={job_id} request_informational={req_ok}")
                    if not req_ok:
                        print(f"[{ts()}] No Request informational button. Skip.")
                        try:
                            page.screenshot(path=os.path.join(out_dir, f"skipped_no_info_btn_{job_id}.png"), full_page=True)
                        except Exception:
                            pass
                        skipped += 1
                        continue

                    page.goto(aboutme_url(job_id), wait_until="domcontentloaded")
                    page.wait_for_timeout(900)

                    body_text = page.text_content("body") or ""
                    role_context = extract_jd_like_text(body_text)

                    cit_skip, cit_reason = requires_us_person_or_citizen(body_text)
                    if cit_skip:
                        print(f"[{ts()}] decision=skip requires_us_person_or_citizen hit={cit_reason}")
                        try:
                            page.screenshot(path=os.path.join(out_dir, f"skipped_usperson_{job_id}.png"), full_page=True)
                        except Exception:
                            pass
                        skipped += 1
                        page.goto(SEARCH_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(900)
                        continue

                    do_apply, reason = should_apply(title, card_text, role_context)
                    print(f"[{ts()}] decision={reason}")
                    if not do_apply:
                        if DEBUG_FILTERING:
                            print(f"[{ts()}] SKIP DEBUG title={title}")
                            print(f"[{ts()}] card_text_preview={card_text[:FILTER_DEBUG_PREVIEW_CHARS]}")
                            print(f"[{ts()}] role_ctx_preview={role_context[:FILTER_DEBUG_PREVIEW_CHARS]}")
                        try:
                            page.screenshot(path=os.path.join(out_dir, f"skipped_{job_id}.png"), full_page=True)
                        except Exception:
                            pass
                        skipped += 1
                        page.goto(SEARCH_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(900)
                        continue

                    score = compute_score(title, card_text, role_context)
                    if score >= HIGH_SCORE_THRESHOLD:
                        line = format_role_line(job_id, title, score)
                        high_score_hits.append(line)
                        print(f"[{ts()}] HIGH SCORE detected (score={score} >= {HIGH_SCORE_THRESHOLD})")
                        print(line)

                        if MODE == "interactive":
                            interactive_high_score_flow(page, job_id, title, score, out_dir)
                        else:
                            try:
                                page.screenshot(path=os.path.join(out_dir, f"highscore_{job_id}.png"), full_page=True)
                            except Exception:
                                pass

                        skipped += 1
                        page.goto(SEARCH_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(900)
                        continue

                    ok_edit, edit_reason = interest_field_editable(page)
                    if not ok_edit:
                        print(f"[{ts()}] decision=skip interest_field_not_editable reason={edit_reason}")
                        try:
                            page.screenshot(path=os.path.join(out_dir, f"skipped_not_editable_{job_id}.png"), full_page=True)
                        except Exception:
                            pass
                        skipped += 1
                        page.goto(SEARCH_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(900)
                        continue

                    why = gen_why_interested_with_retry(title)
                    print(f"[{ts()}] Generated Why interested:")
                    print(why)
                    print("")

                    filled_len, _ = robust_fill_interest(page, why)
                    print(f"[{ts()}] Filled interest-blub length={filled_len}")
                    try:
                        page.screenshot(path=os.path.join(out_dir, f"filled_{job_id}.png"), full_page=True)
                    except Exception:
                        pass

                    page.goto(review_url(job_id), wait_until="domcontentloaded")
                    page.wait_for_timeout(900)

                    submit_btn = page.get_by_role("button", name="Submit").first
                    submit_btn.wait_for(timeout=60000)
                    submit_btn.scroll_into_view_if_needed(timeout=10000)

                    try:
                        page.screenshot(path=os.path.join(out_dir, f"review_{job_id}.png"), full_page=True)
                    except Exception:
                        pass

                    if AUTO_SUBMIT:
                        submit_btn.click()
                        page.wait_for_timeout(1500)
                        try:
                            page.screenshot(path=os.path.join(out_dir, f"submitted_{job_id}.png"), full_page=True)
                        except Exception:
                            pass
                        print(f"[{ts()}] Submitted job_id={job_id}")
                        applied += 1
                    else:
                        input("On review page. Submit manually in browser, then press Enter to continue...")

                    processed += 1
                    page.goto(SEARCH_URL, wait_until="domcontentloaded")
                    page.wait_for_timeout(900)

                except SystemExit as e:
                    print(f"[{ts()}] {e}")
                    raise
                except Exception as e:
                    processed += 1
                    print(f"[{ts()}] EXCEPTION on tile p{page_index}#{k}: {e}")
                    traceback.print_exc()
                    try:
                        page.screenshot(path=os.path.join(out_dir, f"exception_p{page_index}_{k}.png"), full_page=True)
                    except Exception:
                        pass
                    try:
                        page.goto(SEARCH_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(900)
                    except Exception:
                        pass
                    continue

            moved = click_next_page_if_possible(page)
            if not moved:
                break
            page_index += 1

        print(f"\n[{ts()}] Done. Logs in: {out_dir}")
        print(f"[{ts()}] applied={applied} skipped={skipped} processed={processed}")

        # Send high score summary email (auto mode always; interactive optional)
        if high_score_hits:
            subject = f"[BUZOU] High score roles found ({len(high_score_hits)})"
            body = "High score roles (not auto applied):\n\n" + "\n\n".join(high_score_hits) + f"\n\nLogs: {out_dir}\nTime: {datetime.now()}\n"
            if MODE == "interactive":
                choice = input("Send high score summary email? (y/N): ").strip().lower()
                if choice == "y":
                    send_email(subject, body)
            else:
                send_email(subject, body)

        if MODE == "interactive":
            input("Browser kept open. Press Enter to close...")

        ctx.close()

if __name__ == "__main__":
    run()
