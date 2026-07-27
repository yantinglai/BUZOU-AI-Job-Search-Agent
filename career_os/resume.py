from __future__ import annotations

from pathlib import Path

from .models import Job, ResumeArtifact, ResumeMode


class ResumeError(ValueError):
    pass


class ResumeGenerator:
    """Resume boundary for Career OS.

    MVP supports existing resumes. The interface deliberately reserves
    generate-tailored so the previous resume-generator design can be added
    without changing the Ashby adapter.
    """

    SUPPORTED_SUFFIXES = {".pdf"}

    def generate(
        self,
        *,
        job: Job,
        mode: ResumeMode,
        existing_resume_path: str | None = None,
    ) -> ResumeArtifact:
        if mode == "generate-tailored":
            raise NotImplementedError(
                "Tailored generation is not enabled yet; use mode=use-existing."
            )
        if not existing_resume_path:
            raise ResumeError("existing_resume_path is required")

        path = Path(existing_resume_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise ResumeError(f"Resume does not exist: {path}")
        if path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise ResumeError("MVP accepts PDF resumes only")
        if path.stat().st_size == 0:
            raise ResumeError("Resume file is empty")

        warnings: list[str] = []
        if path.stat().st_size > 5 * 1024 * 1024:
            warnings.append("Resume is larger than 5 MB and may be rejected by an ATS.")

        return ResumeArtifact(pdf_path=path, mode=mode, warnings=warnings)
