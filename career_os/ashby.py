from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from .models import ApplicationPayload


class AshbyFillError(RuntimeError):
    pass


def _visible(locator: Locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def _field_by_label(page: Page, label: str) -> Locator:
    # Ashby embeds can vary across companies, so prefer accessible labels and
    # fall back to locating an input inside a container containing the label.
    direct = page.get_by_label(re.compile(re.escape(label), re.I))
    if _visible(direct):
        return direct.first

    container = page.locator(
        "label, [data-testid*='field'], [class*='field'], [class*='Field']"
    ).filter(has_text=re.compile(re.escape(label), re.I))
    if container.count() > 0:
        candidate = container.first.locator("input, textarea, select").first
        if _visible(candidate):
            return candidate
    return page.locator("__career_os_missing_field__")


def _fill_text(field: Locator, value: str) -> None:
    tag = field.evaluate("el => el.tagName.toLowerCase()")
    input_type = (field.get_attribute("type") or "").lower()
    if tag == "select":
        field.select_option(label=value)
    elif input_type in {"checkbox", "radio"}:
        field.check()
    else:
        field.fill(value)


def _select_option_by_question(page: Page, question: str, value: str) -> bool:
    field = _field_by_label(page, question)
    if _visible(field):
        try:
            _fill_text(field, value)
            return True
        except Exception:
            pass

    group = page.locator("fieldset, [role='group'], [class*='field']").filter(
        has_text=re.compile(re.escape(question), re.I)
    )
    if group.count() == 0:
        return False
    option = group.first.get_by_text(re.compile(rf"^{re.escape(value)}$", re.I))
    if option.count() == 0:
        return False
    option.first.click()
    return True


class AshbyBrowserFiller:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open_application(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(1200)
        apply_button = self.page.get_by_role(
            "button", name=re.compile(r"apply|apply now", re.I)
        )
        if _visible(apply_button):
            apply_button.first.click()
            self.page.wait_for_timeout(800)

    def fill(self, payload: ApplicationPayload) -> dict[str, Any]:
        filled: list[str] = []
        missing: list[str] = []

        resume = self.page.locator("input[type='file']").first
        if _visible(resume):
            resume.set_input_files(Path(payload.resume_path))
            filled.append("Resume")
        else:
            missing.append("Resume")

        for label, value in payload.answers.items():
            if not value:
                continue
            if "sponsor" in label.lower():
                ok = _select_option_by_question(self.page, label, str(value))
            else:
                field = _field_by_label(self.page, label)
                ok = _visible(field)
                if ok:
                    try:
                        _fill_text(field, str(value))
                    except Exception:
                        ok = False
            (filled if ok else missing).append(label)

        return {
            "filled": filled,
            "missing": missing,
            "review_required": payload.review_required,
            "submit_clicked": False,
        }

    def assert_submit_not_clicked(self) -> None:
        # Intentionally no submit method in the MVP.
        return None
