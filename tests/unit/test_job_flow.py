import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from src import job_store
from src.graph import app_graph
from src.job_store import JobStatus

TRIAGE_DESTRUCTIVE = (
    "analysis: Request to delete a specific user's data\n"
    "intent_type: data_deletion\n"
    "risk_level: CRITICAL\n"
    "confidence: 0.95\n"
    "risk_reason: Irreversible user data removal"
)
TRIAGE_OPERATIONAL = (
    "analysis: Payment service DB timeouts with DB CPU at 95%\n"
    "intent_type: operational_issue\n"
    "risk_level: HIGH\n"
    "confidence: 0.85\n"
    "risk_reason: Service degradation, nothing destructive requested"
)
SUPERVISOR_TRIAGE = (
    "next_agent: triage\nconfidence: 0.5\nrisk_level: LOW\nreason: no analysis yet"
)
SUPERVISOR_REMEDIATOR = (
    "next_agent: remediator\nconfidence: 0.7\nrisk_level: MEDIUM\nreason: investigation done"
)
SUPERVISOR_FINISH = (
    "next_agent: finish\nconfidence: 0.7\nrisk_level: MEDIUM\nreason: all done"
)


def _response(content: str) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.tool_calls = []
    return message


@pytest.fixture(autouse=True)
def _clear_jobs():
    job_store._jobs.clear()
    yield
    job_store._jobs.clear()


@pytest.fixture
def mocks():
    """Patch every agent's bound llm so nothing touches the network."""
    with (
        patch("src.agents.triage_agent.llm") as triage,
        patch("src.agents.supervisor_agent.llm") as supervisor,
        patch("src.agents.investigator_agent.llm") as investigator,
        patch("src.agents.investigator_agent.llm_with_tools") as investigator_tools,
        patch("src.agents.remediate_agent.llm") as remediator,
    ):
        investigator_tools.invoke.return_value = _response("")
        investigator.invoke.return_value = _response("Investigation report: nothing found")
        remediator.invoke.return_value = _response("Suggested Action: none")

        def _route(prompt: str) -> MagicMock:
            """Mirror what the real supervisor prompt yields for each state."""
            if "triage_analysis: (none)" in prompt:
                return _response(SUPERVISOR_TRIAGE)
            return _response(SUPERVISOR_FINISH)

        supervisor.invoke.side_effect = _route
        yield {
            "triage": triage,
            "supervisor": supervisor,
            "investigator": investigator,
            "remediator": remediator,
        }


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def _wait_for(client, job_id, *statuses, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.02)
    pytest.fail(f"job {job_id} never reached {statuses}, last={body}")


def _submit(client, message):
    response = client.post("/alert", json={"message": message})
    assert response.status_code == 202
    return response.json()["job_id"]


def test_alert_returns_job_id(client, mocks):
    mocks["triage"].invoke.return_value = _response(TRIAGE_OPERATIONAL)
    job_id = _submit(client, "payment-service DB timeout")
    assert job_id
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_unknown_job_is_404(client, mocks):
    assert client.get("/jobs/nope").status_code == 404


def test_destructive_alert_pauses_before_investigator(client, mocks):
    mocks["triage"].invoke.return_value = _response(TRIAGE_DESTRUCTIVE)

    job_id = _submit(client, "delete user data named teja")
    body = _wait_for(client, job_id, JobStatus.PAUSED_FOR_APPROVAL.value)

    assert body["paused_before"] == ["investigator"]
    assert body["needs_approval"] is True
    assert body["intent_type"] == "data_deletion"
    assert "BLOCKED: Destructive intent detected" in body["report"]
    mocks["investigator"].invoke.assert_not_called()


def test_approve_resumes_without_rerunning_supervisor_llm(client, mocks):
    mocks["triage"].invoke.return_value = _response(TRIAGE_DESTRUCTIVE)

    job_id = _submit(client, "delete user data named teja")
    _wait_for(client, job_id, JobStatus.PAUSED_FOR_APPROVAL.value)
    # Only the pre-triage routing call has happened; the destructive gate itself
    # short-circuits before any LLM call, so parking costs nothing extra.
    calls_at_pause = mocks["supervisor"].invoke.call_count

    approve = client.post(f"/jobs/{job_id}/approve", json={"decision": "approve"})
    assert approve.status_code == 200
    _wait_for(client, job_id, JobStatus.FINISHED.value)

    # Resuming did not replay the supervisor decision that caused the pause: the only
    # new call is the fresh decision made after the investigator returned.
    assert mocks["supervisor"].invoke.call_count == calls_at_pause + 1
    # Investigation ran exactly once, and the gate did not re-trip into a second pause.
    assert mocks["investigator"].invoke.call_count == 1


def test_reject_leaves_run_parked(client, mocks):
    mocks["triage"].invoke.return_value = _response(TRIAGE_DESTRUCTIVE)

    job_id = _submit(client, "delete user data named teja")
    _wait_for(client, job_id, JobStatus.PAUSED_FOR_APPROVAL.value)

    reject = client.post(f"/jobs/{job_id}/approve", json={"decision": "reject"})
    assert reject.status_code == 200
    assert client.get(f"/jobs/{job_id}").json()["status"] == JobStatus.REJECTED.value

    snapshot = app_graph.get_state({"configurable": {"thread_id": job_id}})
    assert snapshot.next == ("investigator",)
    mocks["investigator"].invoke.assert_not_called()


def test_approving_a_job_that_is_not_paused_is_409(client, mocks):
    mocks["triage"].invoke.return_value = _response(TRIAGE_OPERATIONAL)

    job_id = _submit(client, "payment-service DB timeout")
    _wait_for(client, job_id, JobStatus.FINISHED.value)

    response = client.post(f"/jobs/{job_id}/approve", json={"decision": "approve"})
    assert response.status_code == 409


def test_operational_alert_runs_straight_through(client, mocks):
    mocks["triage"].invoke.return_value = _response(TRIAGE_OPERATIONAL)
    seen = []

    original_get = job_store.get

    def _recording_get(job_id):
        job = original_get(job_id)
        seen.append(job.status)
        return job

    with patch.object(job_store, "get", _recording_get):
        job_id = _submit(client, "payment-service DB Connection Timeout, CPU 95% high")
        body = _wait_for(client, job_id, JobStatus.FINISHED.value)

    assert body["needs_approval"] is False
    assert JobStatus.PAUSED_FOR_APPROVAL not in seen
    assert mocks["investigator"].invoke.call_count == 1


def test_concurrent_jobs_do_not_block_each_other(client, mocks):
    def _slow_triage(_prompt):
        time.sleep(0.4)
        return _response(TRIAGE_DESTRUCTIVE)

    mocks["triage"].invoke.side_effect = _slow_triage

    slow_id = _submit(client, "delete user data named teja")
    fast_id = _submit(client, "delete user records for bob")

    # Both progress concurrently: neither blocking triage call stalls the other's polling.
    _wait_for(client, slow_id, JobStatus.PAUSED_FOR_APPROVAL.value)
    _wait_for(client, fast_id, JobStatus.PAUSED_FOR_APPROVAL.value)

    assert slow_id != fast_id
