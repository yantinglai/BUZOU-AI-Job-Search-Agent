# BUZOU-AI-Job-Search-Agent


**buzou.com** is a survival tool for laid-offers:
I’m not leaving quietly — but I’m also not wasting time clicking applications manually.

---

## What it does (today)

- Scrapes roles from the internal job portal
- Extracts key fields (title, location, job id, hiring manager, recruiter)
- Scores and ranks roles based on my preferences
- Exports results to `jobs.json` / `jobs.csv`

---

## Roadmap (next)

- Improve extraction reliability (job id / title / description)
- Generate a “why I’m a match” draft for each role
- Auto-monitor new roles on a schedule
- (Later) one-click apply workflows

---

## BUZOU Job Search AI Agent Setup

Playwright based internal job search + auto fill + optional auto submit for Amazon Internal Transfer (IT) portal.

This script:

1. Opens the IT Search page and iterates through role cards
2. Filters out roles based on heuristics (frontend heavy roles outside Bay Area, internships, US person / clearance requirements)
3. Opens AboutMe page for the role, generates a **Why interested** paragraph using OpenAI API, and fills the field
4. Opens Review page and optionally clicks **Submit** automatically (auto mode)

---

## Quick Start

### 1) Create a venv and install dependencies

    python -m venv .venv
    source .venv/bin/activate

    pip install playwright
    playwright install chromium

### 2) Set OpenAI API key

    export OPENAI_API_KEY="YOUR_KEY"
    # optional
    export OPENAI_MODEL="gpt-4o-mini"

### 3) First run (interactive)

Interactive mode is useful to confirm selectors and ensure your login session is stored in the persistent Chrome profile directory.

    MODE=interactive PROFILE_DIR=./chrome_profile \
    python Fullstack_agent.py

### 4) Auto mode (auto submit)

Auto mode will auto fill and click Submit for eligible roles.

    MODE=auto PROFILE_DIR=./chrome_profile \
    TYPE_DELAY_MS=3 \
    python Fullstack_agent.py

---

## Notes

- This repo uses Playwright persistent context, so cookies/session are stored in `PROFILE_DIR`.
- If you are not logged in, the script will wait for you to complete AEA/login in the opened browser (auto mode included).

---

## Personal preferences (current config)

Right now this repo is tuned for **my** search:

- Prefer: Bay Area / NYC / LA
- Avoid: Seattle
- Avoid: frontend / full-stack
- Prefer: systems + AI/ML infra signals

The goal is to make this configurable so anyone can plug in their own priorities.

---

Have fun and happy coding!
