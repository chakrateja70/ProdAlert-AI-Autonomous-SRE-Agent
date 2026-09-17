# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

ProdAlert AI is an autonomous SRE agent. A P1 alert fires in production, a webhook hits our FastAPI
service, a Celery worker runs a LangGraph agent that reads logs and past incidents, and the agent
posts a root cause to Slack, creates a Jira ticket, and (only for allow-listed actions) runs a fix.

Goal: cut MTTR from ~30 min to under 2 min. Full spec lives in the PRD; this file is the working
contract for the code.

## Tech stack

- Python 3.11, dependencies managed with `uv` (never `pip install` directly)
- FastAPI + Pydantic v2 (ingestion API)
- Celery + Redis (queues: `agent_queue`, `ingestion_queue`)
- LangGraph + LangChain + Anthropic SDK (the agent)
- Pinecone (vectors), Postgres + SQLAlchemy + Alembic (jobs, alerts, reviews)
- Loki + Prometheus (log and metric sources — Phase 1 is Loki only)
- Ruff, mypy (strict), pytest, pytest-cov, structlog, LangSmith

## Repo layout

```
src/prodalert/
  api/            FastAPI app, routes, webhook auth, schemas
  agent/
    graph.py      LangGraph StateGraph wiring
    state.py      AgentState (typed, single source of truth)
    nodes/        log_analyzer.py, diagnosis.py, action.py
    prompts/      system prompts, versioned
  tools/          loki.py, prometheus.py, pinecone_search.py, jira.py, slack.py, remediation.py
  queue/          celery_app.py, tasks.py
  db/             models.py, migrations/
  config.py       Settings (pydantic-settings, env only)
tests/
  unit/  integration/  eval/
```

## Commands

```bash
make up            # docker-compose: api, worker, redis, postgres
make test          # pytest + coverage (must stay >= 80%)
make lint          # ruff check + ruff format --check + mypy
make fake-alert SERVICE=payments-api TYPE=memory_high
make eval          # run the golden dataset (needs API keys)
uv add <package>   # add a dependency
```

Run `make lint` and `make test` before saying a task is done.

## Conventions

- Type hints on every function; `mypy --strict` must pass. No bare `Any` in agent state or tool
  signatures.
- All I/O in the API layer is async. Celery tasks are sync; use `asyncio.run()` at the task boundary.
- Config only through `config.py` Settings. Never read `os.environ` elsewhere, never hardcode URLs.
- Logging is structlog only, JSON, and every log line inside a job must carry `job_id`. No `print`.
- Custom exceptions in `errors.py`; never `except Exception: pass`.
- Tool functions are plain typed Python functions with docstrings; LangChain decorates them. Keep
  business logic out of node code so tools can be unit tested alone.
- Conventional commits (`feat:`, `fix:`, `chore:`). Small PRs.

## Agent rules (do not weaken these)

- `AgentState` is the only thing passed between nodes. Add a field there rather than smuggling state
  through globals or closures.
- The Diagnosis node must return structured JSON: `root_cause`, `evidence` (log lines or incident
  ids), `confidence` (0-1), `suggested_action`. Parse and validate with Pydantic; on parse failure,
  retry once, then escalate to a human.
- Never let the model generate shell commands or kubectl arguments. Remediation is a fixed allow-list
  of named actions with typed parameters.
- Auto-remediation runs only when all of these hold: action is allow-listed, `confidence >= 0.85`,
  `AUTO_REMEDIATION_ENABLED` is true, per-service rate limit not hit, one action per incident.
- Every claim in a diagnosis needs evidence from retrieved logs or incidents. If evidence is missing,
  return "not enough evidence" rather than guessing.
- Token budget is 20k per incident: Haiku summarises logs, Sonnet only diagnoses, send top-5
  retrieved incidents (not 100), cache the system prompt.
- Redact secrets, tokens, emails and card numbers before sending anything to the model.

## Ingestion rules

- Webhook signature check, Pydantic schema check, P1 only. Respond in under 200 ms.
- Dedupe with `SET dedupe:<sha256(service+alert_type+namespace)> <job_id> NX EX 900`. If the lock
  exists, increment the existing job's `alert_count` and return `status: deduplicated`.
- Rate limits: 1 active job per service, 5 runs per service per hour, 20 runs globally per 10 min.
- Job timeout is 120 s; on timeout, fall back to normal paging.

## Testing

- Unit tests mock Jira, Slack, Loki, Pinecone and the Anthropic API. No network calls in unit tests.
- Integration tests run against docker-compose with fake alerts.
- Eval tests use the golden dataset in `tests/eval/data/`; they run in CI only when prompts, models
  or retrieval code change. A drop of more than 3 accuracy points blocks the merge.
- New tool or node means a new test file. Coverage must not drop below 80%.

## Local setup

Copy `.env.example` to `.env` and fill in: `ANTHROPIC_API_KEY`, `PINECONE_API_KEY`, `JIRA_TOKEN`,
`SLACK_BOT_TOKEN`, `LOKI_URL`, `PROMETHEUS_URL`, `LANGSMITH_API_KEY`, `DATABASE_URL`, `REDIS_URL`.
Keep `AUTO_REMEDIATION_ENABLED=false` in local and dev.

## Things not to do

- Do not commit `.env`, API keys, or real log snapshots containing customer data.
- Do not call production Jira, Slack or Kubernetes from tests or local runs; use the sandbox
  workspace and the `--dry-run` remediation mode.
- Do not add a new remediation action without a test and an entry in the allow-list config.
- Do not change prompt files without running `make eval` and noting the score in the PR.