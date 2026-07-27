from __future__ import annotations

from .models import ApplicationPayload, Candidate, Job, ResumeArtifact


PROJECT_NOTE = (
    "One project I’m proud of was improving the reliability and performance of "
    "Amazon Redshift’s Vacuum workflows. I worked on the storage layer where "
    "Vacuum reorganizes table data to reclaim space and improve query performance. "
    "I built large-scale system and performance tests that uncovered seven critical "
    "issues before release, and designed a sliding-window anomaly detector that "
    "automatically created SEV-2 tickets when Vacuum activity deviated from expected "
    "behavior. I also improved migration tooling for our test infrastructure, "
    "increasing automated Jenkins-to-Hydra conversion from roughly 20% to 90%."
)


def build_cursor_storage_payload(
    *, job: Job, candidate: Candidate, resume: ResumeArtifact
) -> ApplicationPayload:
    answers = {
        "Name": candidate.full_name,
        "Email": candidate.email,
        "Phone": candidate.phone,
        "LinkedIn Profile": candidate.linkedin,
        "GitHub Profile": candidate.github,
        "Please share a project you are proud of": PROJECT_NOTE,
        "Will you now or in the future require visa sponsorship?": (
            "Yes" if candidate.sponsorship_required else "No"
        ),
    }
    if candidate.referral_email:
        answers["Referral email"] = candidate.referral_email

    return ApplicationPayload(
        job=job,
        candidate=candidate,
        resume_path=str(resume.pdf_path),
        answers=answers,
        review_required=["gender", "race_ethnicity", "veteran_status"],
    )
