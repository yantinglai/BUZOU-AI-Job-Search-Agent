from playwright.sync_api import sync_playwright
import re
import json
from datetime import datetime
import os
import traceback
import csv
from typing import Optional, Dict, Tuple, List, Any
import sqlite3
import hashlib
from urllib.parse import urlparse

# ----------------------------
# Config
# ----------------------------

DEBUG_SCORING = False  # set True to print keyword-hit debug per job


def origin_from_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def encode_filter_values(values: list[str]) -> str:
    # match your URL style: spaces become %2520 and items are joined by %7C%7C%7C
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

KEEP_BROWSER_OPEN = True
SEEN_DB_PATH = os.path.join("outputs", "seen_jobs.sqlite3")

# Set to something small like 7 if you want periodic re-processing even if hash unchanged.
# If you don't want stale reprocessing, keep huge:
REFRESH_DAYS = 10**9

# Pagination controls
MAX_PAGES = 30                # safety cap
PROCESS_ALL_CARDS_PER_PAGE = True
MAX_CARDS_PER_PAGE = 9999     # only used if PROCESS_ALL_CARDS_PER_PAGE=False
ROLE_LINK_PREFIX = origin_from_url(SEARCH_URL).rstrip("/") + "/role/"

# ----------------------------
# Helpers
# ----------------------------


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def is_logged_in_search_page(page) -> bool:
    u = (page.url or "").lower()
    if "login" in u or "signin" in u or "auth" in u:
        return False
    # Search page sidebar container or any role card are good signals
    if page.locator("#search-navigation-sidebar-section").count() > 0:
        return True
    if page.locator("div[id^='role-card-']").count() > 0:
        return True
    return False


def compute_detail_hash(detail_text: str) -> str:
    normalized = clean(detail_text).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


# ----------------------------
# Scoring (FIXED)
# ----------------------------

def _phrase_hits(phrases: List[str], s: str) -> List[str]:
    s_low = (s or "").lower()
    hits = []
    for p in phrases:
        if p.lower() in s_low:
            hits.append(p)
    return hits


def _regex_hits(patterns: List[str], s: str) -> List[str]:
    hits = []
    for pat in patterns:
        if re.search(pat, s or "", flags=re.IGNORECASE):
            hits.append(pat)
    return hits


def score_role(text: str, location_hint: str):
    """
    Returns: (score:int, reasons:list[str], debug:dict)
    - reasons: short human explanations
    - debug: what matched (optional, helpful to tune)
    """
    t_raw = text or ""
    t_low = t_raw.lower()

    score = 0
    reasons: List[str] = []

    debug: Dict[str, Any] = {}

    # -------- location (IMPORTANT: location_hint should be ONLY the "US, XX, City" line) --------
    loc = (location_hint or "").lower()

    bay_area_markers = [
        "san francisco", "mountain view", "palo alto", "east palo alto",
        "sunnyvale", "san jose", "cupertino", "santa clara",
        "menlo park", "union city", "los gatos",
        "us, ca",
    ]
    la_markers = [
        "los angeles", "irvine", "culver city", "santa monica",
        "burbank", "san diego", "lax", "us, ca, los angeles",
    ]
    seattle_markers = ["seattle", "bellevue", "redmond", "kirkland", "us, wa"]

    loc_bucket = None
    if any(x in loc for x in bay_area_markers):
        score += 30
        reasons.append("Bay Area location")
        loc_bucket = "bay_area"
    elif any(x in loc for x in la_markers):
        score += 18
        reasons.append("LA location")
        loc_bucket = "la"
    elif any(x in loc for x in seattle_markers):
        score -= 6
        reasons.append("Seattle (lower priority)")
        loc_bucket = "seattle"
    else:
        loc_bucket = "other"

    debug["loc"] = {"hint": location_hint, "bucket": loc_bucket}

    # -------- UI signals (strong vs weak; SAFE word-boundary matching) --------
    UI_STRONG_PATTERNS = [
        r"\bfront[- ]?end\b",
        r"\bfrontend\b",
        r"\bfull[- ]?stack\b",
        r"\breact\b",
        r"\bnext\.js\b",
        r"\bvue\b",
        r"\bangular\b",
        r"\btypescript\b",
        r"\bjavascript\b",
        r"\bhtml\b",
        r"\bcss\b",
        r"\bios\b",
        r"\bandroid\b",
        r"\bswift\b",
        r"\bkotlin\b",
        r"\bjsp\b",
        r"\bfreemarker\b",
        r"\bweb (app|apps|features)\b",
    ]
    UI_WEAK_PATTERNS = [
        r"\bui\b",
        r"\bux\b",
    ]

    ui_strong = _regex_hits(UI_STRONG_PATTERNS, t_raw)
    ui_weak = _regex_hits(UI_WEAK_PATTERNS, t_raw)

    debug["ui"] = {"strong": ui_strong, "weak": ui_weak}

    # -------- Engines / Data infra signals (ODA should hit hard) --------
    ENGINES_PHRASES = [
        "query engine", "optimizer", "query runtime", "execution engine",
        "logical planning", "physical execution", "cost based", "cbo",
        "trino", "presto", "spark", "velox",
        "iceberg", "hudi", "delta", "open table format",
        "parquet", "orc", "storage connector", "connector",
        "vectorized", "spill", "shuffle", "join reordering",
        "query processing", "parsing", "logical plan", "physical plan",
    ]
    engines_hits = _phrase_hits(ENGINES_PHRASES, t_raw)
    if engines_hits:
        score += 35
        reasons.append("Engines / data infra signals")

    debug["engines"] = engines_hits

    # -------- AI/ML infra / GenAI signals --------
    AI_PHRASES = [
        "neuron", "trainium", "inferentia",
        "compiler", "runtime", "kernel", "accelerator",
        "distributed training", "inference",
        "llm", "genai", "generative ai", "prompt", "rag",
        "agent", "agents", "agentic",
        "model evaluation", "evaluation metrics",
        "inference optimization", "performance optimization",
    ]
    ai_hits = _phrase_hits(AI_PHRASES, t_raw)
    if ai_hits:
        score += 30
        reasons.append("AI/ML infra / GenAI signals")

    debug["ai"] = ai_hits

    # -------- Systems / distributed signals (still useful, but not too generic) --------
    SYSTEMS_PHRASES = [
        "distributed", "fault-tolerant", "fault tolerant", "scalable",
        "reliability", "observability", "performance", "latency",
        "throughput", "storage", "replication", "consistency", "durability",
        "monitoring", "on-call", "operational excellence",
        "high availability", "availability", "slo", "sla",
    ]
    sys_hits = _phrase_hits(SYSTEMS_PHRASES, t_raw)
    if sys_hits:
        score += 18
        reasons.append("Distributed systems")

    debug["systems"] = sys_hits

    # -------- UI penalty (no longer nukes everything) --------
    ui_penalty = 0
    if ui_strong:
        ui_penalty -= 25
    elif ui_weak:
        ui_penalty -= 8

    # If this role is clearly Engines/AI/Systems, reduce UI penalty (avoid false negatives)
    if (engines_hits or ai_hits or sys_hits) and ui_penalty < 0:
        ui_penalty = int(ui_penalty * 0.5)

    if ui_penalty < 0:
        score += ui_penalty
        reasons.append("UI/full-stack signals")

    debug["ui_penalty"] = ui_penalty
    debug["final_score"] = score

    return score, reasons[:3], debug


# ----------------------------
# Database helpers
# ----------------------------
def init_jobs_db(db_path: str = SEEN_DB_PATH):
    ensure_dir(os.path.dirname(db_path))
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            job_link TEXT,
            title TEXT,

            first_seen_ts TEXT NOT NULL,
            last_seen_ts  TEXT NOT NULL,
            seen_count    INTEGER NOT NULL DEFAULT 0,

            last_detail_ts   TEXT,
            last_detail_hash TEXT
        )
    """)
    conn.commit()
    return conn


def db_get_job(conn, job_id: str) -> Optional[Dict[str, Optional[str]]]:
    cur = conn.execute("""
        SELECT job_id, last_detail_hash, last_detail_ts
        FROM jobs
        WHERE job_id = ?
    """, (job_id,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "job_id": row[0],
        "last_detail_hash": row[1],
        "last_detail_ts": row[2],
    }


def db_touch_seen(conn, job_id: str, title: Optional[str], job_link: Optional[str]):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("""
        INSERT INTO jobs(job_id, job_link, title, first_seen_ts, last_seen_ts, seen_count)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(job_id) DO UPDATE SET
            last_seen_ts = excluded.last_seen_ts,
            seen_count   = jobs.seen_count + 1,
            title        = COALESCE(excluded.title, jobs.title),
            job_link     = COALESCE(excluded.job_link, jobs.job_link)
    """, (job_id, job_link, title, now, now))
    conn.commit()


def db_update_detail(conn, job_id: str, detail_hash: str):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("""
        UPDATE jobs
        SET last_detail_ts = ?, last_detail_hash = ?
        WHERE job_id = ?
    """, (now, detail_hash, job_id))
    conn.commit()


def should_process(prev: Optional[Dict[str, Optional[str]]], new_hash: str) -> bool:
    """Return True if job is new or updated, or stale enough to refresh."""
    if prev is None:
        return True

    old_hash = prev.get("last_detail_hash") if prev else None
    if not old_hash:
        return True

    if new_hash != old_hash:
        return True  # updated content

    last_ts = prev.get("last_detail_ts") if prev else None
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            age_days = (datetime.now() - last_dt).days
            if age_days >= REFRESH_DAYS:
                return True
        except Exception:
            return True

    return False


# ----------------------------
# Extractors (lightweight + robust for this UI)
# ----------------------------
def extract_job_id(detail: str) -> Optional[str]:
    if not detail:
        return None
    # e.g. "Job ID: 3157673"
    m = re.search(r"\bJob\s*ID\s*:\s*(\d+)\b", detail, re.IGNORECASE)
    if m:
        return m.group(1)

    # fallback: your original method
    s = detail
    idx = s.lower().find("job id")
    if idx == -1:
        return None
    i = idx + len("job id")
    n = len(s)
    while i < n and not s[i].isdigit():
        i += 1
    if i >= n:
        return None
    j = i
    while j < n and s[j].isdigit():
        j += 1
    digits = s[i:j]
    return digits if digits else None


def extract_location_hint_from_card(meta_raw: str) -> str:
    """
    IMPORTANT: return only a concise location line (e.g. 'US, CA, East Palo Alto'),
    NOT the entire meta text. This prevents false matches like 'platform' -> 'la'.
    """
    s = meta_raw or ""

    # Most common pattern on cards: "US, CA, East Palo Alto"
    m = re.search(r"\bUS,\s*([A-Z]{2}),\s*([A-Za-z][A-Za-z ]+)", s)
    if m:
        state = m.group(1)
        city = clean(m.group(2))
        return f"US, {state}, {city}"

    # Another possible pattern: "USA, CA, East Palo Alto"
    m2 = re.search(r"\bUSA,\s*([A-Z]{2}),\s*([A-Za-z][A-Za-z ]+)", s)
    if m2:
        state = m2.group(1)
        city = clean(m2.group(2))
        return f"US, {state}, {city}"

    # Fallback: try to find any "US, XX," substring line-ish
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("US, "):
            return clean(ln)
        if ln.startswith("USA, "):
            return clean(ln.replace("USA, ", "US, "))

    return ""


# ----------------------------
# Output
# ----------------------------
def save_results(out_dir: str, results: List[Dict[str, Any]], prefix: str = "all_roles"):
    ensure_dir(out_dir)

    json_path = os.path.join(out_dir, f"{prefix}.json")
    json_top10_path = os.path.join(out_dir, f"{prefix}_top10.json")
    csv_path = os.path.join(out_dir, f"{prefix}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(json_top10_path, "w", encoding="utf-8") as f:
        json.dump(results[:10], f, indent=2, ensure_ascii=False)

    fieldnames = [
        "rank", "job_id", "job_link", "title",
        "score", "reasons",
        "page_num",
        "meta",
        "detail_preview",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for idx, r in enumerate(results, start=1):
            w.writerow({
                "rank": idx,
                "job_id": r.get("job_id"),
                "job_link": r.get("job_link"),
                "title": r.get("title"),
                "score": r.get("score"),
                "reasons": "; ".join(r.get("reasons") or []),
                "page_num": r.get("page_num"),
                "meta": r.get("meta"),
                "detail_preview": r.get("detail_preview"),
            })

    print(f"[OUTPUT] Saved {len(results)} jobs to folder: {out_dir}")


# ----------------------------
# Pagination helpers
# ----------------------------
def get_first_card_id(sidebar) -> Optional[str]:
    first = sidebar.locator("div[id^='role-card-']").first
    if first.count() == 0:
        return None
    return first.get_attribute("id")


def click_next_page(page) -> bool:
    """
    Returns True if we clicked next successfully.
    Returns False if next is not available or disabled.
    """
    # Preferred: button with aria-label "Next page"
    next_btn = page.locator("button[aria-label='Next page']").first
    if next_btn.count() == 0:
        # fallback: aria-label contains Next
        next_btn = page.locator("button[aria-label*='Next']").first
        if next_btn.count() == 0:
            return False

    # Check disabled
    disabled_attr = next_btn.get_attribute("disabled")
    aria_disabled = next_btn.get_attribute("aria-disabled")
    if disabled_attr is not None:
        return False
    if aria_disabled and aria_disabled.lower() == "true":
        return False

    next_btn.click()
    return True


# ----------------------------
# Main scrape
# ----------------------------
def run():
    def ts():
        return datetime.now().strftime("%H:%M:%S")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("outputs", f"run_{run_id}")
    ensure_dir(out_dir)
    print(f"[{ts()}] Output folder: {out_dir}")
    print(f"[{ts()}] Role link prefix: {ROLE_LINK_PREFIX}")

    conn = None

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir="./chrome_profile",
                headless=False
            )
            page = ctx.new_page()
            page.goto(SEARCH_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            if not is_logged_in_search_page(page):
                print(
                    f"[{ts()}] Not logged in. Please finish login/AEA in browser.")
                page.goto(origin_from_url(SEARCH_URL) + "/",
                          wait_until="domcontentloaded")
                input("Finish login/AEA in the opened browser, then press Enter here...")
                page.goto(SEARCH_URL, wait_until="domcontentloaded")

            page.wait_for_load_state("networkidle")
            page.wait_for_selector(
                "#search-navigation-sidebar-section", timeout=60000)

            # DB
            conn = init_jobs_db()

            results: List[Dict[str, Any]] = []
            seen_this_run = set()

            sidebar = page.locator("#search-navigation-sidebar-section").first

            # Right panel: anchor on "Job ID" and take a big ancestor container
            page.get_by_text("Job ID", exact=False).first.wait_for(
                timeout=30000)
            right = page.get_by_text("Job ID", exact=False).first.locator(
                "xpath=ancestor::div[4]")

            for page_num in range(1, MAX_PAGES + 1):
                page.wait_for_timeout(700)
                page.wait_for_selector(
                    "#search-navigation-sidebar-section", timeout=60000)

                sidebar = page.locator(
                    "#search-navigation-sidebar-section").first
                cards = sidebar.locator("div[id^='role-card-']")

                total = cards.count()
                print(
                    f"[{ts()}] Page {page_num}: detected role cards in DOM: {total}")

                if total == 0:
                    # Sometimes needs a little time; try once more
                    page.wait_for_timeout(1200)
                    total = cards.count()
                    print(f"[{ts()}] Page {page_num}: retry count: {total}")
                    if total == 0:
                        break

                limit = total if PROCESS_ALL_CARDS_PER_PAGE else min(
                    total, MAX_CARDS_PER_PAGE)
                print(f"[{ts()}] Page {page_num}: scanning {limit} cards")

                for k in range(limit):
                    try:
                        card = cards.nth(k)
                        card.scroll_into_view_if_needed(timeout=8000)

                        meta_raw = card.inner_text(timeout=15000)
                        meta_lines = [ln.strip()
                                      for ln in meta_raw.splitlines() if ln.strip()]
                        title = meta_lines[0] if meta_lines else f"role_{page_num}_{k}"

                        card.click()
                        page.wait_for_timeout(350)

                        # Wait for right panel to be populated and include Job ID
                        detail = ""
                        for _ in range(12):
                            txt = clean(right.text_content() or "")
                            if len(txt) >= 120 and "job id" in txt.lower():
                                detail = txt
                                break
                            page.wait_for_timeout(250)

                        if not detail:
                            print(
                                f"[{ts()}] WARN: empty right panel on page {page_num} card {k}")
                            continue

                        job_id = extract_job_id(detail)
                        if not job_id:
                            continue

                        job_link = f"{ROLE_LINK_PREFIX}{job_id}"

                        # per-run de-dupe
                        if job_id in seen_this_run:
                            continue
                        seen_this_run.add(job_id)

                        # persistent de-dupe
                        prev = db_get_job(conn, job_id)
                        db_touch_seen(conn, job_id, title, job_link)

                        new_hash = compute_detail_hash(detail)

                        # if unchanged (and refresh not triggered), skip emitting into json
                        if not should_process(prev, new_hash):
                            continue

                        location_hint = extract_location_hint_from_card(
                            meta_raw)
                        score, reasons, debug = score_role(
                            detail, location_hint)

                        if DEBUG_SCORING:
                            print(
                                f"\n[{ts()}] DEBUG score job_id={job_id} title={title}")
                            print(f"  location_hint: {location_hint}")
                            print(f"  score: {score} reasons: {reasons}")
                            print(
                                f"  debug: {json.dumps(debug, ensure_ascii=False)[:1200]}")

                        results.append({
                            "title": title,
                            "job_id": job_id,
                            "job_link": job_link,
                            "score": score,
                            "reasons": reasons,
                            "page_num": page_num,
                            "meta": clean(meta_raw)[:400],
                            "detail_preview": detail[:240] + "...",
                            "detail_full": detail,
                            "scoring_debug": debug if DEBUG_SCORING else None,
                            "location_hint": location_hint,
                        })

                        db_update_detail(conn, job_id, new_hash)

                    except Exception as e:
                        print(
                            f"[{ts()}] EXCEPTION page {page_num} card {k}: {e}")
                        traceback.print_exc()
                        page.screenshot(
                            path=os.path.join(
                                out_dir, f"exception_p{page_num}_k{k}.png"),
                            full_page=True
                        )
                        continue

                # Try go next page
                first_id_before = get_first_card_id(sidebar)
                clicked = click_next_page(page)
                if not clicked:
                    print(
                        f"[{ts()}] No next page (or disabled). Stopping at page {page_num}.")
                    break

                # Wait for first card to change (page actually advanced)
                ok = False
                for _ in range(40):
                    sidebar2 = page.locator(
                        "#search-navigation-sidebar-section").first
                    new_first = get_first_card_id(sidebar2)
                    if new_first and new_first != first_id_before:
                        ok = True
                        break
                    page.wait_for_timeout(250)

                if not ok:
                    print(
                        f"[{ts()}] WARN: Next page click did not change first card id; continuing anyway.")

            # sort and save
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            print(f"\n[{ts()}] ===== TOP 10 RESULTS (NEW/UPDATED ONLY) =====")
            print(json.dumps(results[:10], indent=2, ensure_ascii=False))

            save_results(out_dir, results, prefix="all_roles")

            if conn:
                conn.close()

            print(f"[{ts()}] Done.")
            if KEEP_BROWSER_OPEN:
                input("Browser kept open. Press Enter to close it...")
            ctx.close()

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] FATAL: {e}")
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    run()
