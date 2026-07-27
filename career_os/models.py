from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ResumeMode = Literal["use-existing", "generate-tailored"]


@dataclass(frozen=True)
class Job:
    company: str
    title: str
    url: str
    description: str = ""
    location: str = ""


@dataclass(frozen=True)
class Candidate:
    full_name: str
    email: str
    phone: str
    linkedin: str
    github: str
    sponsorship_required: bool
    referral_email: str = ""


@dataclass(frozen=True)
class ResumeArtifact:
    pdf_path: Path
    mode: ResumeMode
    warnings: list[str] = field(default_factory=list)


@dataclass
class ApplicationPayload:
    job: Job
    candidate: Candidate
    resume_path: str
    answers: dict[str, Any]
    review_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
