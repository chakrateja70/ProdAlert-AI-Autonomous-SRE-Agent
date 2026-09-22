import asyncio
import uuid
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel

from src import job_store
from src.config import config
from src.errors import JobNotFoundError, JobNotPausedError
from src.graph import GATED_NODES, app_graph
from src.job_store import JobStatus

app = FastAPI(title="ProdAlert-AI")

# Langfuse tracing enable (optional but powerful)
langfuse_handler = None
try:
    from langfuse.langchain import CallbackHandler

    if config.LANGFUSE_SECRET_KEY and config.LANGFUSE_PUBLIC_KEY:
        # CallbackHandler reads LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY / LANGFUSE_HOST
        # from the environment itself; config.py's load_dotenv() already put them there.
        langfuse_handler = CallbackHandler()
except ImportError:
    pass

print("✅ Langfuse tracing enabled" if langfuse_handler else "⚠️ Langfuse not configured, running without tracing")


class AlertInput(BaseModel):
    message: str


class ApprovalInput(BaseModel):
    decision: Literal["approve", "reject"]


class HealthResponse(BaseModel):
    status: str
    version: str


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    paused_before: list[str]
    needs_approval: bool | None
    supervisor_decision: str | None
    risk_level: str | None
    intent_type: str | None
    triage_analysis: str | None
    report: str | None
    remediation: str | None
    error: str | None


# asyncio only holds weak references to tasks, so an in-flight job can be garbage
# collected mid-run without this.
_running_tasks: set[asyncio.Task[None]] = set()


def _spawn(job_id: str, payload: Any) -> None:
    task = asyncio.create_task(_run_job(job_id, payload))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


def _run_config(job_id: str) -> dict[str, Any]:
    run_config: dict[str, Any] = {"configurable": {"thread_id": job_id}}
    if langfuse_handler:
        run_config["callbacks"] = [langfuse_handler]
    return run_config


async def _run_job(job_id: str, payload: Any) -> None:
    """Drive the graph until it finishes or parks on a step a human must approve.

    Pauses land before every gated node, but only the ones carrying needs_approval stop
    here - the rest resume immediately so low-risk alerts flow through unattended.
    """
    run_config = _run_config(job_id)
    job_store.update(job_id, status=JobStatus.RUNNING)
    try:
        while True:
            # to_thread: every node makes a blocking ChatOpenAI.invoke() call, which would
            # otherwise stall the event loop and every other in-flight job.
            await asyncio.to_thread(
                app_graph.invoke,
                payload,
                config=run_config,
                interrupt_before=GATED_NODES,
            )
            snapshot = app_graph.get_state(run_config)
            values = dict(snapshot.values)

            if not snapshot.next:
                job_store.update(job_id, status=JobStatus.FINISHED, state=values, paused_before=[])
                print(f"✅ job {job_id}: finished")
                return

            if values.get("needs_approval"):
                job_store.update(
                    job_id,
                    status=JobStatus.PAUSED_FOR_APPROVAL,
                    state=values,
                    paused_before=list(snapshot.next),
                )
                print(f"⏸️ job {job_id}: paused for approval before {snapshot.next}")
                return

            job_store.update(job_id, state=values, paused_before=list(snapshot.next))
            print(f"▶️ job {job_id}: auto-resuming before {snapshot.next} (no approval needed)")
            payload = None
    except Exception as exc:  # background task boundary - nothing upstream to propagate to
        job_store.update(job_id, status=JobStatus.ERROR, error=str(exc))
        print(f"💥 job {job_id}: failed with {exc!r}")


@app.exception_handler(JobNotFoundError)
def _job_not_found(request: Request, exc: JobNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"job not found: {exc}"})


@app.exception_handler(JobNotPausedError)
def _job_not_paused(request: Request, exc: JobNotPausedError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": f"job is not awaiting approval: {exc}"})


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ProdAlert-AI is running", version="v1")


@app.post("/alert", response_model=JobAcceptedResponse, status_code=202)
async def handle_alert(payload: AlertInput) -> JobAcceptedResponse:
    job_id = uuid.uuid4().hex
    print(f"🚨 Alert received: {payload.message} | job_id={job_id}")
    job_store.create(job_id)

    initial_state = {
        "job_id": job_id,
        "alert": payload.message,
        "retries": 0,
        "confidence": 0.0,
        "triage_analysis": "",
        "logs": "",
        "metrics": "",
        "remediation": "",
        "report": "",
        "agent_visits": {},
    }
    _spawn(job_id, initial_state)
    return JobAcceptedResponse(job_id=job_id, status=JobStatus.QUEUED.value)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    job = job_store.get(job_id)
    state = job.state
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        paused_before=job.paused_before,
        needs_approval=state.get("needs_approval"),
        supervisor_decision=state.get("supervisor_decision"),
        risk_level=state.get("risk_level"),
        intent_type=state.get("intent_type"),
        triage_analysis=state.get("triage_analysis"),
        report=state.get("report"),
        remediation=state.get("remediation"),
        error=job.error,
    )


@app.post("/jobs/{job_id}/approve", response_model=JobAcceptedResponse)
async def approve_job(job_id: str, payload: ApprovalInput) -> JobAcceptedResponse:
    job = job_store.get(job_id)
    if job.status is not JobStatus.PAUSED_FOR_APPROVAL:
        raise JobNotPausedError(f"{job_id} is {job.status.value}")

    if payload.decision == "reject":
        # Checkpoint stays parked and is never resumed, so nothing downstream runs.
        job_store.update(job_id, status=JobStatus.REJECTED)
        print(f"🛑 job {job_id}: rejected by human")
        return JobAcceptedResponse(job_id=job_id, status=JobStatus.REJECTED.value)

    print(f"👍 job {job_id}: approved by human, resuming")
    _spawn(job_id, Command(resume={"approved": True}))
    return JobAcceptedResponse(job_id=job_id, status=JobStatus.RUNNING.value)


if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)