# Copilot instructions for Talli

Talli is a Norwegian-first filing assistant for simple Norwegian holding companies (`AS`). It is a hybrid codebase: a **deterministic Python filing core** plus a **Next.js web app** that delegates the compliance math to that core. Read `CONTEXT.md` (domain glossary) and `docs/adr/` before making non-trivial changes.

## Architecture: Python core is the source of truth, the web app delegates to it

This is the single most important thing to understand, and it spans multiple files.

- **`holding_core/` (Python)** owns all statutory/accounting logic: narrow double-entry ledger (`ledger.py`), holding actions (`holding_actions.py`), RF-1086 / Aksjonærregisteroppgaven generation (`rf1086*.py`), annual accounts + tax return (`annual.py`), validation and readiness gates (`validation.py`, `readiness.py`), submission state (`submission.py`), and the in-memory workspace model (`workspace.py`). Ledger math, tax calculations, validation rules, filing payloads, and submission state **must stay deterministic and live here** (ADR-0003, ADR-0007, ADR-0008).
- **`holding_cli/main.py`** exposes the core as a `talli` CLI with subcommands that read JSON from stdin (e.g. `render-rf1086-preview`, `simulate-rf1086-submission`, `validate-rf1086-xml`, `validate-case`).
- **`app/` (Next.js 16 / React 19, App Router)** is the UI, persistence (Supabase), and orchestration layer. For filing-critical computations it does **not** re-implement the math — it shells out to the Python core:
  ```ts
  // app/lib/rf1086.ts, app/lib/rf1086-submission.ts
  spawnSync(process.env.TALLI_PYTHON_BIN || "python3",
            ["-m", "holding_cli.main", "<command>", "--stdin-json"], …)
  ```
  When adding filing logic, extend `holding_core` + a CLI subcommand and call it from `app/lib/*.ts`; do not port compliance math into TypeScript.

## Build, test, lint

Python is managed with **uv** (`pyproject.toml`, `uv.lock`, Python ≥ 3.12). Node/Next is managed with **npm** (`package.json`).

- **Python env:** `uv sync` (creates `.venv` with pydantic).
- **Python tests** (`tests/test_*.py`, stdlib `unittest`):
  - All: `uv run python -m unittest discover -s tests`
  - Single file: `uv run python tests/test_ledger_and_actions.py`
  - Single test: `uv run python tests/test_ledger_and_actions.py HoldingActionTest.test_share_sale_reduces_position_and_calculates_gain`
- **Node tests** (`tests/*.test.mjs`, `node:test` run through `--experimental-strip-types`, so they import `.ts`/`.mjs` directly with no build step). These run **without `npm install`**:
  - Single: `npm run test:<name>` (one script per test, see `package.json`) or `node --experimental-strip-types --test tests/<file>.test.mjs`
  - Full rehearsal suite: `npm run test:launch-rehearsal`
  - **Tests that cross the bridge** (e.g. `npm run test:rf1086:persisted`) spawn Python. The system `python3` usually lacks `holding_core`/pydantic, so run them with `TALLI_PYTHON_BIN="$PWD/.venv/bin/python"`.
- **Web build / typecheck / dev** require `npm install` first (`node_modules` is not committed; the `node:test` suites don't need it):
  - `npm run dev` · `npm run build` · `npm run typecheck` (`tsc --noEmit`)
- **Lint:** Python only — `uvx ruff check .` (`[tool.ruff]` line-length 110). There is no JS/TS linter configured.
- **Browser test:** `npm run test:browser-owner` (Playwright; needs `npm install`).

## Conventions specific to this repo

- **Norwegian-first product language (ADR-0004).** User-facing strings, filing names, and codes use Norwegian authority/accounting terms — `aksjonærregisteroppgaven`, `årsregnskap`, `skattemelding for AS`, messages like `"Organisasjonsnummer må ha 9 sifre."`. Use the canonical terms (and avoid the listed synonyms) defined in `CONTEXT.md`; don't anglicize domain concepts.
- **Narrow scope is intentional.** The product only supports a "simple holding AS" (no VAT, payroll, invoicing, or complex share events). Unsupported cases are explicitly **blocked / escalated / warned** via a support boundary and readiness gate rather than handled — preserve that behavior instead of adding general-accounting features.
- **`holding_core` ↔ `app/lib` parity.** Many domains exist on both sides (e.g. `rf1086.py` ↔ `app/lib/rf1086.ts`) with parallel Python and Node test files. Keep authoritative computation in Python and treat TS as the caller/UI; when changing behavior, update both layers and both test suites.
- **TS authored for strip-types.** `app/lib/*.ts` is consumed directly by the Node test runner. One module is split into runtime + types: `app/lib/workspace.mjs` and `app/lib/workspace.d.ts` — keep them in sync.
- **Supabase access.** Env vars are in `.env.example` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` — server-only, `DATABASE_URL`, `DIRECT_DATABASE_URL`). The web app uses the SSR server client (`app/lib/supabase/server.ts`) and Next.js Server Actions (`app/actions.ts` starts with `"use server"`). DB migrations live in `supabase/migrations/`; the reference schema is `docs/supabase/talli_mvp_schema.sql`.
- **Filing specs are evidence-backed.** Official schemas and authority maps live in `docs/filing/` (e.g. `aksjonaerregisteroppgaveHovedskjema.xsd`); generated XML is validated against these XSDs via the CLI. Don't invent payload fields — trace them to the maps/evidence registers in `docs/filing/`.

## Where to look

- `CONTEXT.md` — domain glossary (canonical terms + synonyms to avoid).
- `docs/adr/` — architectural decisions (why the Python core, narrow ledger, Norwegian-first, owner-managed filing).
- `PLAN.md` and `docs/prd/` — product/engineering plan and PRDs.
- `AGENTS.md` → `docs/agents/` — issue-tracker, triage-label, and domain-doc conventions for agent workflows.
