from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.errors import JobNotFoundError


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    FINISHED = "finished"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class Job:
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    state: dict[str, Any] = field(default_factory=dict)
    paused_before: list[str] = field(default_factory=list)
    error: str | None = None


# ponytail: module-level dict, single process only - job state is lost on restart (same
# limitation as MemorySaver); swap for a shared store only if restart-survival is needed.
_jobs: dict[str, Job] = {}


def create(job_id: str) -> Job:
    job = Job(job_id=job_id)
    _jobs[job_id] = job
    return job


def get(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return job


def update(job_id: str, **changes: Any) -> Job:
    job = get(job_id)
    for key, value in changes.items():
        setattr(job, key, value)
    return job
