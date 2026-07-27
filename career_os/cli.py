from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from .ashby import AshbyBrowserFiller
from .models import Candidate, Job
from .payload import build_cursor_storage_payload
from .resume import ResumeGenerator

CURSOR_STORAGE_URL = "https://cursor.com/careers/software-engineer-storage"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill the Cursor Storage application and stop before submit."
    )
    parser.add_argument("--resume", required=True, help="Path to an existing PDF resume")
    parser.add_argument("--profile-dir", default="./chrome_profile_ashby")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output", default="./output/cursor-storage/payload.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    job = Job(
        company="Cursor / Anysphere",
        title="Software Engineer, Storage",
        url=CURSOR_STORAGE_URL,
        location="San Francisco or New York",
    )
    candidate = Candidate(
        full_name="Yanting Lai",
        email="laiyanting.neu@gmail.com",
        phone="(206) 370-2304",
        linkedin="https://linkedin.com/in/yantinglai",
        github="https://github.com/yantinglai",
        sponsorship_required=True,
    )

    resume = ResumeGenerator().generate(
        job=job,
        mode="use-existing",
        existing_resume_path=args.resume,
    )
    payload = build_cursor_storage_payload(job=job, candidate=candidate, resume=resume)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload.to_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=args.headless,
        )
        page = context.pages[0] if context.pages else context.new_page()
        filler = AshbyBrowserFiller(page)
        filler.open_application(job.url)
        report = filler.fill(payload)
        print(json.dumps(report, indent=2))
        print("\nReview the browser. Career OS will NOT click Submit.")
        if not args.headless:
            input("Press Enter to close the browser...")
        context.close()


if __name__ == "__main__":
    main()
