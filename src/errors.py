class JobNotFoundError(Exception):
    """Raised when a job_id has no entry in the job store."""


class JobNotPausedError(Exception):
    """Raised when approve/reject is called on a job that is not paused for approval."""
