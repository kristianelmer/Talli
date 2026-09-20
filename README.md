# Talli

Accounting and annual reporting for owners of Norwegian holding companies.

Talli guides a company owner through recording investments, dividends, shareholder loans and administrative costs, then preparing the year's reports. Its scope is a simple holding AS: a company that owns investments and has relatively few transactions. The interface uses Norwegian accounting terms and asks about company events before generating accounting entries.

The project covers the shareholder register statement (*aksjonærregisteroppgaven*), company tax return (*skattemelding for AS*) and annual accounts (*årsregnskap*).

**Status:** Under active development. The repository includes filing simulations, authority integration code and recorded test-environment evidence. Live filing is subject to separate production-access, validation and release gates. See the [launch status](docs/launch/production-launch-rehearsal.md).

## Skatteetaten and Altinn integration

The hardest part of building Talli has been connecting the accounting workflows to Skatteetaten and Altinn. This involves authentication through Maskinporten, permission to act for a company, authority-specific filing formats and a submission process that continues across several requests.

For example, the company-tax test flow creates a filing instance, uploads the XML envelope, waits for file scanning, starts validation and records the authority's response. An accepted filing advances to owner confirmation. The workflow keeps track of completed steps so it can resume after an interruption.

| Part | Code to explore |
| --- | --- |
| Token requests, signing and authority scopes | [Maskinporten adapter](apps/backend/src/talli_backend/adapters/maskinporten.py) |
| Company identity, system-user access and rights | [Altinn system-user adapter](apps/backend/src/talli_backend/adapters/altinn_system_user.py) |
| Upload, validation and owner-confirmation flow | [Company-tax rehearsal](apps/backend/src/talli_backend/modules/company_tax_filing/rehearsal.py) |
| Rules that determine whether a filing is ready | [Company-tax readiness](apps/backend/src/talli_backend/modules/company_tax_filing/readiness.py) |

Integration contracts and test evidence are documented for [shareholder reporting](docs/filing/aksjonaerregisteroppgaven-phase-0-map.md), [company tax](docs/filing/company-tax-return-authority-map.md) and [annual accounts](docs/filing/annual-accounts-authority-map.md).

## Accounting and validation

- **Guided transactions:** typed inputs and posting rules for supported holding-company actions, including opening balances and shareholder loans.
- **Ledger:** balanced debit/credit entries, a draft-to-posted workflow, reversals and an audit trail.
- **Annual preparation:** year-end questions, calculated totals, filing previews and readiness checks.
- **Validation:** public and synthetic test cases with expected totals. Results distinguish valid cases, warnings, mismatches, blocked cases and unsupported situations.

Start with [holding actions](holding_core/holding_actions.py), the [ledger](holding_core/ledger.py), or the [annual-validation harness](holding_core/validation.py) and its [tests](tests/test_annual_validation.py).

## Structure

The frontend is a Next.js/React application written in TypeScript. Business operations go through a generated API client to a Python/FastAPI backend. PostgreSQL and Supabase provide persistence and authentication.

```text
apps/web/                  Next.js interface
apps/backend/              FastAPI routes, business modules and provider adapters
packages/talli-api-client/  Generated TypeScript API client
contracts/openapi/         Committed API contract
holding_core/              Accounting models and offline filing preparation
holding_cli/               Command-line simulations and validation
supabase/                  Database migrations and access policies
tests/                     Fixtures and cross-component tests
docs/                      Integration evidence, decisions and runbooks
```

The [domain glossary](CONTEXT.md), [product scope](PRODUCT.md) and [architecture decisions](docs/adr/) explain the boundaries in more detail.

## Run an offline example

Use Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/). The backend dependency set includes PyICU; install the native prerequisites described in the [backend setup notes](apps/backend/README.md) before syncing dependencies. CI uses Python 3.12.

```bash
git clone https://github.com/kristianelmer/Talli.git
cd Talli
uv sync --locked

uv run python -m holding_cli.main validate-annual-public-data \
  --case tests/fixtures/annual_validation/simple_holding_pass.json \
  --json
```

This validates a synthetic company case and prints a JSON report. It does not connect to Skatteetaten or Altinn. To examine a mismatch, replace the fixture with `simple_holding_mismatch.json`; the command reports the difference and exits with a nonzero status.

## Run the web application

Use Node.js 24, Python and uv. Configure the development database, authentication and backend settings using [`.env.example`](.env.example). The web scripts read the repository-root `.env`; the backend needs its settings in the process environment.

```bash
npm ci
uv sync --project apps/backend --locked
```

Start the backend with its development environment configured:

```bash
uv run --project apps/backend uvicorn talli_backend.main:app \
  --app-dir apps/backend/src --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
TALLI_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

See the [web README](apps/web/README.md) and [backend README](apps/backend/README.md) for component setup. Authority test flows require separate test credentials and configuration; starting the app does not enable live filing.

## Checks

```bash
# Local annual-validation behavior
uv run python -m unittest tests.test_annual_validation -v

# TypeScript checks and the web/backend contract
npm run typecheck
npm run test:boundary
```

More targeted commands are listed in [`package.json`](package.json). Database lifecycle tests require a disposable test database; authority rehearsals have their own environment and access requirements. The [release workflow](.github/workflows/release-gate.yml) defines the broader checks used before release.
