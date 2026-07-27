from pathlib import Path

import pytest

from career_os.models import Candidate, Job
from career_os.payload import build_cursor_storage_payload
from career_os.resume import ResumeError, ResumeGenerator


def test_existing_resume_and_payload(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.pdf"
    resume_path.write_bytes(b"%PDF-1.4\nCareer OS fixture")
    job = Job(company="Cursor", title="Storage", url="https://example.com")
    candidate = Candidate(
        full_name="Yanting Lai",
        email="laiyanting.neu@gmail.com",
        phone="(206) 370-2304",
        linkedin="https://linkedin.com/in/yantinglai",
        github="https://github.com/yantinglai",
        sponsorship_required=True,
    )

    artifact = ResumeGenerator().generate(
        job=job, mode="use-existing", existing_resume_path=str(resume_path)
    )
    payload = build_cursor_storage_payload(
        job=job, candidate=candidate, resume=artifact
    )

    assert payload.resume_path == str(resume_path.resolve())
    assert payload.answers["Will you now or in the future require visa sponsorship?"] == "Yes"
    assert "seven critical" in payload.answers["Please share a project you are proud of"]


def test_missing_resume_fails() -> None:
    job = Job(company="Cursor", title="Storage", url="https://example.com")
    with pytest.raises(ResumeError):
        ResumeGenerator().generate(
            job=job,
            mode="use-existing",
            existing_resume_path="does-not-exist.pdf",
        )
