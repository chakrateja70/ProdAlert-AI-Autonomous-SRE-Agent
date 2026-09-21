# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ProdAlert AI is an autonomous SRE agent. A P1 alert comes in via `POST /alert`, a LangGraph agent
reads logs and metrics, and it posts back a root cause and a remediation plan (advisory only, never
auto-executed). Goal: cut MTTR from ~30 min to under 2 min.

Full spec: `files/PRD ProdAlert AI – Autonomous SRE Agent.pdf`. The PDF cannot be read without
poppler installed, so treat "Target architecture" and "Agent rules" below as the working contract
until you can read the PRD directly.

## Current state — verify before assuming a module exists

The app runs end to end (`uv run python main.py`, then `POST /alert`), but most of the CLAUDE.md-
shaped target architecture below is still aspirational. Check what's actually on disk rather than
assuming a described module is there.

What exists and runs:

- [main.py](main.py) — FastAPI app. `GET /` for health, `POST /alert` invokes the compiled graph
  and returns `triage_decision`/`confidence`/`report`. `uvicorn.run("main:app", ...)` under
  `__main__` for local dev with reload.
- [src/config.py](src/config.py) — the one place that calls `load_dotenv()` and exposes settings as
  `config.<NAME>`. `OPENAI_API_KEY` is required (raises on missing); Langfuse keys are optional.
  Every other module should import `config` from here, not read `os.environ` or call
  `load_dotenv()` itself.
- [src/otel_setup.py](src/otel_setup.py) — wires an OpenTelemetry `TracerProvider` + OTLP exporter
  pointed at Langfuse's OTEL endpoint and instruments the FastAPI app. Called once from `main.py`.
- [src/state.py](src/state.py) — `OverallState` TypedDict, the shared state passed between nodes.
  Has no `job_id` field, so anything reading `state["job_id"]` (see the tools below) never finds
  one — it's always `None` until a field/caller is added.
- [src/graph.py](src/graph.py) — `StateGraph` wiring: `triage` → (`investigate` | `escalate` | END)
  via `router()`, `investigate` → `remediate` → END. Routing is driven entirely by
  `state["confidence"]` and `state["triage_decision"]`, both set by `triage_agent`.
- [src/agents/triage_agent.py](src/agents/triage_agent.py), [investigator_agent.py](src/agents/investigator_agent.py),
  [remediate_agent.py](src/agents/remediate_agent.py) — the three graph nodes. Each parses its LLM
  response with substring checks (`"investigate" in content.lower()`), not structured/validated
  output.
- [src/tools/logs_search.py](src/tools/logs_search.py), [metrics_search.py](src/tools/metrics_search.py)
  — `@tool`-decorated functions reading `files/sample_logs.txt` / `files/sample_metrics.txt` (stand-ins
  for Loki/Prometheus). Both resolve their file path relative to `Path(__file__)`, not CWD. Both
  take an injected `runtime: ToolRuntime` param (excluded from the model-visible args schema),
  currently used only to `print()` a debug line with `job_id` — always `None` today (see above).
- [try_logs_search.py](try_logs_search.py) — standalone script that calls `get_metrics`/`get_logs`
  directly and prints the results; not a pytest file.
- `tests/`, `.claude/skills/{sre-triage,sre-investigator,sre-remediator}/` — empty directories, no
  test files or skill content yet.
- `README.md` — empty.

Known gaps/breakage to fix rather than build around:

- `.env` has `LANGFUSE_BASE_URL`, but `config.py` reads `LANGFUSE_HOST`. The mismatch means
  `config.LANGFUSE_HOST` silently falls back to its hardcoded default
  (`https://cloud.langfuse.com`) instead of any custom value in `.env`. Align the var name in one
  place before relying on a non-default Langfuse host.
- [src/otel_setup.py](src/otel_setup.py) sends OTLP spans to Langfuse's OTEL endpoint with
  `headers={}` — Langfuse's OTEL ingestion needs Basic Auth (public/secret key) in the headers, so
  traces are currently sent with no credentials and likely rejected. `langfuse.langchain.CallbackHandler`
  (used in `main.py`) is the integration that actually authenticates via `config`; OTEL export is a
  second, separate path that isn't wired to the same keys yet.
- No structured-output parsing anywhere: `triage_agent` and `remediate_agent` regex/substring-match
  raw LLM text instead of returning Pydantic-validated JSON. See "Agent rules" below for the target
  shape.
- No retry-then-escalate-on-parse-failure logic.
- Remediation is fully LLM-authored free text (including a literal `kubectl rollout restart ...`
  example in the prompt), not a fixed allow-list of typed actions — this directly conflicts with
  the target architecture's remediation rule; treat any remediation-node change as needing that
  allow-list, not just a prompt tweak.
- No dedupe, rate limiting, webhook signature check, queueing, Postgres, Pinecone, or Slack/Jira
  integration. `POST /alert` is the only entry point and runs synchronously in-request.

## Commands

There is no Makefile, Dockerfile or CI config. Use `uv` directly:

```bash
uv run python main.py                  # run the FastAPI app (uvicorn, reload on) on :8000
uv run python try_logs_search.py       # call get_logs/get_metrics directly, print the responses
uv run pytest                          # tests (none exist yet)
uv run pytest tests/unit/test_x.py::test_name   # a single test, once test files exist
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run mypy src                        # no mypy config yet; strict is the goal, currently unenforced
uv add <package>                       # add a dependency (never `pip install`)
```

`uv run pytest` needs `[tool.pytest.ini_options] pythonpath = ["."]` in `pyproject.toml` (already
present) so that `from src...` imports resolve — pytest does not add the repo root to `sys.path`
on its own.

`requirements.txt` is a plain mirror of `pyproject.toml`'s `dependencies` for tools that expect it
(e.g. `pip install -r requirements.txt`). `pyproject.toml` + `uv.lock` are the real source of
truth — update both together (`uv add <package>` updates `pyproject.toml`/`uv.lock`; mirror the
same line into `requirements.txt` by hand).

Python is pinned to 3.12 via `.python-version`.

## Target architecture

Ingestion (FastAPI) → queue → LangGraph agent → Slack / Jira / remediation. Queueing, Slack and
Jira don't exist yet; `POST /alert` calls the compiled graph synchronously in the request handler.

The graph is `triage` → `investigate` → `remediate`, with `escalate` as the human-handoff branch
whenever `confidence < 0.8`. `OverallState` in [src/state.py](src/state.py) is meant to be the
single object passed between nodes — add fields there rather than smuggling state through globals
or closures.

Phase 1 uses local sample files (`files/sample_logs.txt`, `files/sample_metrics.txt`) instead of
Loki/Prometheus. Celery/Redis, Postgres/Alembic and Pinecone are planned, not present — do not
import them until they are added with `uv add`.

## Agent rules (do not weaken these)

- `OverallState` is the only thing passed between nodes.
- The diagnosis/investigation step must eventually return structured JSON: `root_cause`, `evidence`
  (log lines or incident ids), `confidence` (0-1), `suggested_action`. Parse and validate with
  Pydantic; on parse failure, retry once, then escalate to a human. Current nodes do neither —
  treat this as the direction to move node output in, not the existing behavior.
- Never let the model generate shell commands or kubectl arguments. Remediation must be a fixed
  allow-list of named actions with typed parameters — `remediate_agent.py`'s free-text LLM output
  (which includes example `kubectl` commands in its own prompt) does not meet this bar yet.
- Auto-remediation runs only when all of these hold: action is allow-listed, `confidence >= 0.85`,
  `AUTO_REMEDIATION_ENABLED` is true, per-service rate limit not hit, one action per incident. No
  action is auto-executed today (remediation is advisory text), so none of these gates are wired
  to anything yet — build them alongside the first real remediation action, not after.
- Every claim in a diagnosis needs evidence from retrieved logs or metrics. If evidence is missing,
  return "not enough evidence" rather than guessing.
- Redact secrets, tokens, emails and card numbers before sending anything to the model.
- Keep business logic in `src/tools/` as plain typed functions with docstrings so they unit-test
  without a graph; nodes stay thin.

## Conventions

- Type hints on every function; aim for `mypy --strict` (not currently enforced — no mypy config
  and several files fail basic ruff checks today; run `uv run ruff check .` to see current state).
- Config only through `src/config.py`'s `config` object. Never call `load_dotenv()` or read
  `os.environ` directly anywhere else, never hardcode URLs/paths/keys.
- Logging is meant to end up structlog, JSON, with every log line inside a job carrying `job_id` —
  not wired in yet; the tools' current `print()` debug lines are a placeholder to replace, not a
  pattern to copy.
- Custom exceptions in `errors.py` (doesn't exist yet); never bare `except:` or
  `except Exception: pass` — catch specific exceptions (see `main.py`'s `except ImportError` around
  the optional Langfuse import for the pattern to follow).
- Conventional commits (`feat:`, `fix:`, `chore:`). Small PRs.
- Existing files mix Telugu-English comments. Match the surrounding file's style; don't rewrite
  them as a drive-by.

## Testing

- Unit tests should mock the LLM and file reads. No network calls in unit tests.
- New tool or node means a new test file. `tests/` is currently empty.

## Local setup

Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` (required). `LANGFUSE_SECRET_KEY` /
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_HOST` are optional — leave them blank to run without tracing. Use
the exact names `config.py` reads (`LANGFUSE_HOST`, not `LANGFUSE_BASE_URL` — see the flagged
mismatch above).

## Things not to do

- Do not commit `.env`, API keys, or real log snapshots containing customer data.
- Do not hardcode API keys in source files — load them through `config`.
- Do not call production Jira, Slack or Kubernetes from tests or local runs; use a sandbox
  workspace and `--dry-run` remediation once those integrations exist.
- Do not add a remediation action without a test and an allow-list config entry.
- Keep `AUTO_REMEDIATION_ENABLED=false` in local and dev once that flag is introduced.
