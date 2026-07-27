# Career OS — Ashby MVP

This MVP fills the Cursor **Software Engineer, Storage** application using an existing PDF resume and stops before final submission.

## Safety boundary

The code intentionally has no submit method. It fills known fields, prints missing/review-required fields, and leaves the browser open for human review.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install playwright pytest
playwright install chromium
```

## Run

```bash
python -m career_os.cli \
  --resume /absolute/path/to/Resume_Yanting_Lai_04142026.pdf
```

The command writes a structured payload to:

```text
output/cursor-storage/payload.json
```

It then opens Cursor's application page, uploads the resume, fills recognized fields, and pauses for review.

## Current scope

- Existing PDF resume only (`use-existing`)
- Cursor Storage fixture
- Accessible-label-first field matching with DOM fallback
- Visa sponsorship answer
- Project note based on Redshift Vacuum work
- No final submission

## Next

- Inspect Cursor's live embedded Ashby schema/network traffic
- Replace heuristic question labels with normalized Ashby field paths
- Add a reusable YAML candidate profile
- Restore the tailored resume generator behind the existing `ResumeGenerator` interface
- Add screenshots and validation report
