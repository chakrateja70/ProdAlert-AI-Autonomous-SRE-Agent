# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ProdAlert AI is an autonomous SRE agent. A P1 alert comes in via `POST /alert`, a LangGraph agent reads logs and metrics, and it posts back a root cause and a remediation plan (advisory only, never auto-executed). Goal: cut MTTR from ~30 min to under 2 min.

Full spec: `files/PRD ProdAlert AI – Autonomous SRE Agent.pdf`. The PDF cannot be read without poppler installed, so treat "Target architecture" and "Agent rules" below as the working contract.

## Current state — the actual implementation

The app runs end to end with human-in-the-loop approval and job persistence:

**Core flow:**
- [main.py](main.py) — FastAPI app with async job queue. `POST /alert` returns immediately with a `job_id`; `GET /jobs/{id}` polls status; `POST /jobs/{id}/approve` resumes paused jobs.
  - `GET /health` — health check.
  - `POST /alert` (async, returns 202) — submit alert; jobs run in the background via `asyncio.create_task()`.
  - `GET /jobs/{job_id}` — poll job status (queued/running/paused_for_approval/finished/rejected/error).
  - `POST /jobs/{job_id}/approve` — resume a paused job (body: `{"decision": "approve" | "reject"}`).

**Graph architecture:**
- [src/graph.py](src/graph.py) — `StateGraph` with a supervisor-based router and `interrupt_before` pause/resume. Entry point is `supervisor`, which routes to `triage` / `investigator` / `remediator`, all looping back to supervisor. Nodes are gated by a `MemorySaver` checkpointer so paused state is durable.
- [src/state.py](src/state.py) — `OverallState` TypedDict: `alert`, `job_id`, `triage_analysis`, `intent_type`, `risk_level`, `risk_reason`, `confidence`, `logs`, `metrics`, `remediation`, `report`, `needs_approval`, `next_agent`, etc.

**Agents:**
- [src/agents/triage_agent.py](src/agents/triage_agent.py) — LLM analyst. Outputs `analysis` (1-2 line technical summary), `intent_type` (data_deletion / destructive / operational_issue / performance_degradation / read_only), `risk_level` (LOW / MEDIUM / HIGH / CRITICAL), `confidence` (0-1), `risk_reason`.
- [src/agents/supervisor_agent.py](src/agents/supervisor_agent.py) — LLM router + safety gates.
  - Hard gate 1: if `intent_type in ("data_deletion", "destructive")` and pre-investigation, routes to `investigator` with `needs_approval=True` (pauses for human review).
  - Hard gate 2: if `risk_level == "HIGH"` and `intent_type == "operational_issue"` and pre-investigation, routes to `investigator` with `needs_approval=False` (auto-resumes).
  - Otherwise, LLM decides `next_agent` (triage / investigator / remediator / finish) + `confidence` + `risk_level`.
- [src/agents/investigator_agent.py](src/agents/investigator_agent.py) — LLM with tools. Calls `get_logs` and/or `get_metrics` as needed (not both unconditionally), writes investigation report.
- [src/agents/remediate_agent.py](src/agents/remediate_agent.py) — LLM suggester. Reads investigation report, outputs remediation steps (text only, never auto-executed).

**Job persistence & approval flow:**
- [src/job_store.py](src/job_store.py) — in-memory dict + dataclass tracking job status, state snapshot, and the node paused before (if any). Survives process restarts only if a database is added (currently memory-only; `# ponytail: swap for a shared store if restart-survival is needed`).
- `_run_job()` async loop — auto-resumes past non-approval pauses (low-risk jobs flow unattended), parks on `needs_approval=True` (waits for human via `POST /jobs/{id}/approve`), force-finishes on visit cap exceeded per agent.

**Tools:**
- [src/tools/logs_search.py](src/tools/logs_search.py), [metrics_search.py](src/tools/metrics_search.py) — read `files/sample_logs.txt` / `files/sample_metrics.txt` (stand-ins for Loki/Prometheus).

**Config & setup:**
- [src/config.py](src/config.py) — loads `.env` (call `load_dotenv()` only here). Exposes `config.OPENAI_API_KEY` (required), `config.LANGFUSE_SECRET_KEY/PUBLIC_KEY/HOST` (optional).
- [src/llm_service.py](src/llm_service.py) — `get_llm(model)` singleton factory (`@lru_cache`). Every agent imports `llm = get_llm("model-name")`.
- [src/errors.py](src/errors.py) — custom exceptions: `JobNotFoundError`, `JobNotPausedError`.

**Tests:**
- [tests/conftest.py](tests/conftest.py) — neutralizes `.env` loading so tests never read real API keys; seeds placeholders.
- [tests/unit/test_job_flow.py](tests/unit/test_job_flow.py) — integration tests for pause/approve/reject flow, concurrent jobs, etc. Mocks all LLMs with `MagicMock`.
- `tests/unit/test_triage_agent.py` — unit tests for triage parsing (tests were deleted; rebuild if needed).

## Commands

```bash
uv run python main.py                          # FastAPI app on :8000 with reload
uv run pytest -q                               # run tests
uv run pytest tests/unit/test_job_flow.py -v  # integration tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv add <package>                               # add dependency
```

`pyproject.toml` + `uv.lock` are the source of truth. Mirror new lines into `requirements.txt` by hand.

## High-level architecture

```
POST /alert
    ↓
main.py: create job_id, spawn async _run_job()
    ↓
    └─→ LangGraph auto-resume loop:
        ├─ invoke(interrupt_before=GATED_NODES)
        ├─ snap = get_state()
        ├─ if snap.next is empty → finished
        ├─ if needs_approval=True → paused, wait for POST /jobs/{id}/approve
        └─ else → resume (no human needed)
            ↓
            supervisor_agent
            ├─ hard gate 1: data_deletion/destructive pre-investigation → investigator + needs_approval
            ├─ hard gate 2: HIGH risk operational pre-investigation → investigator + no approval
            └─ LLM router → triage/investigator/remediator/finish
                ↓
                [selected agent node]
                ↓
                loop back to supervisor

POST /jobs/{id}/approve {"decision": "approve"} → resume the paused run
POST /jobs/{id}/approve {"decision": "reject"} → mark rejected, leave checkpoint parked
GET /jobs/{id} → poll status + state snapshot
```

**Key design decisions:**
- Supervisor is the single router; all agents loop back to it. No direct agent-to-agent edges.
- `interrupt_before` gates pause *before* entering a node (not dynamic `interrupt()`), so the paused node's LLM is never re-run on resume.
- Destructive alerts (data_deletion/destructive intent) pause even on first run if pre-investigation, requiring explicit human approval to proceed.
- High-risk operational alerts route to investigation with `needs_approval=False` (auto-resume, no human gate).
- Low-risk / operational alerts never pause (flow straight through to remediation).
- Job store tracks status/state snapshot separately from LangGraph's checkpointer (cheap `GET /jobs/{id}` queries).

## Known gaps & TODOs

- Job store is memory-only. Add a Postgres/SQLite checkpointer when restart-survival is needed.
- No structured-output parsing validation yet. Agents parse with substring/regex; add Pydantic validation if parse failure becomes a problem.
- Remediation is free-text LLM output, not a fixed allow-list of typed actions. Phase 1 is advisory; gates like `confidence >= 0.85` are not yet wired.
- No auto-remediation execution. Only advisory text is returned.
- No Slack/Jira integration, webhook signature check, rate limiting, or dedupe.
- No structured JSON logging yet (placeholder `print()` statements).
- Supervisor has no deterministic fallback if LLM route decision is unparseable — relies on error-handler to mark job as ERROR (edge case, low priority).

## Agent rules (do not weaken)

- `OverallState` is the only thing passed between nodes. No globals, no closures.
- On parse failure (triage, supervisor), retry once, then escalate (triage defaults to `intent_type="destructive"` to fail safe).
- Destructive intents must pause and wait for human approval before investigation runs.
- Every diagnosis claim needs evidence from logs or metrics. Return "insufficient evidence" rather than guessing.
- Redact secrets, tokens, emails, card numbers before sending to the model.
- Keep business logic in `src/tools/` as plain typed functions; nodes stay thin.

## Conventions

- Type hints on every function; goal is `mypy --strict` (not currently enforced).
- Config only via `config` object from `src/config.py`. Never call `load_dotenv()` or read `os.environ` elsewhere.
- LLM clients via `get_llm(model)` from `src/llm_service.py`, never construct `ChatOpenAI()` directly.
- Custom exceptions in `src/errors.py`; never bare `except:` or `except Exception: pass`.
- Conventional commits (`feat:`, `fix:`, `chore:`). Small PRs.

## Local setup

```bash
uv sync
cp .env.example .env
# Fill .env with OPENAI_API_KEY (required); LANGFUSE_* are optional
uv run python main.py  # then POST to /alert
```

## Things not to do

- Do not commit `.env` or API keys.
- Do not add a remediation action without allow-list config (not yet implemented).
- Do not call production Jira/Slack/Kubernetes from tests.
- Do not weaken the agent rules above without explicit approval.
