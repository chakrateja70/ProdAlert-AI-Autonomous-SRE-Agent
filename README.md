# ProdAlert AI — Autonomous SRE Agent

An autonomous SRE agent: a P1 alert comes in, a [LangGraph](https://github.com/langchain-ai/langgraph)
agent reads logs and metrics, and it posts back a root cause and a remediation plan (advisory only,
never auto-executed). Goal: cut MTTR from ~30 min to under 2 min.

Full spec: `files/PRD ProdAlert AI – Autonomous SRE Agent.pdf`.

This is an early-stage project — see [CLAUDE.md](CLAUDE.md) for what's actually implemented versus
still aspirational.

## How it works

```
POST /alert  →  triage  →  investigate  →  remediate  →  response
                   │
                   └──(low confidence)──→  escalate
```

1. **triage** — an LLM call decides `investigate` / `escalate` / `ignore` and a confidence score.
2. **investigate** — if triaged for investigation, an LLM with two tools (`get_logs`, `get_metrics`)
   pulls evidence and writes a root-cause report.
3. **remediate** — an LLM suggests remediation steps from the investigation report (text only; no
   action is ever auto-executed).
4. **escalate** — if confidence is below threshold, the alert is handed off for a human instead.

Logs and metrics currently come from local sample files (`files/sample_logs.txt`,
`files/sample_metrics.txt`), standing in for Loki/Prometheus in a later phase.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
```

Fill in `.env`:

- `OPENAI_API_KEY` — required.
- `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_HOST` — optional. Leave blank to run
  without tracing; fill in to see traces at [cloud.langfuse.com](https://cloud.langfuse.com).

## Running

```bash
uv run python main.py
```

Starts the FastAPI app on `http://localhost:8000` with reload enabled.

- `GET /` — health check.
- `POST /alert` — send an alert through the graph:

  ```bash
  curl -X POST http://localhost:8000/alert \
    -H "Content-Type: application/json" \
    -d '{"message": "payment-service is down with DB Connection Timeout"}'
  ```

  Returns `triage_decision`, `confidence`, and the full `report` text.

To exercise the log/metric tools directly without the API:

```bash
uv run python try_logs_search.py
```

## Development

```bash
uv run ruff check . && uv run ruff format --check .   # lint
uv run mypy src                                        # type check
uv run pytest                                           # tests (none exist yet)
uv add <package>          # add a runtime dependency
uv add --dev <package>    # add a dev/tooling dependency
```

`requirements.txt` mirrors `pyproject.toml`'s `dependencies` for tools that expect a plain
requirements file; `pyproject.toml` + `uv.lock` are the source of truth.

See [CLAUDE.md](CLAUDE.md) for architecture notes, known gaps, and conventions.
