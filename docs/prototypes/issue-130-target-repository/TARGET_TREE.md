# Proposed target repository tree

This is the recommended destination, not a migration sequence.

```text
/
├── AGENTS.md
├── CONTEXT.md
├── apps/
│   ├── backend/                              # independently buildable FastAPI app
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── src/talli_backend/
│   │   │   ├── main.py                      # invokes composition root; no wiring
│   │   │   ├── shared_kernel/               # only primitives approved in #124
│   │   │   ├── modules/
│   │   │   │   └── <capability>/
│   │   │   │       ├── module.json          # enforceable ownership definition
│   │   │   │       ├── MODULE.md            # scoped intent; changes with manifest
│   │   │   │       ├── public/
│   │   │   │       │   ├── __init__.py      # sole cross-capability import path
│   │   │   │       │   ├── commands.py
│   │   │   │       │   ├── queries.py
│   │   │   │       │   ├── errors.py
│   │   │   │       │   ├── ids.py
│   │   │   │       │   └── events.py
│   │   │   │       ├── domain/              # private rules and entities
│   │   │   │       ├── application/         # private use-case implementations
│   │   │   │       ├── ports/               # capability-owned outbound seams
│   │   │   │       ├── persistence/         # owned repositories and mappings
│   │   │   │       ├── migrations/          # same-named owned DB schema
│   │   │   │       └── tests/
│   │   │   │           ├── unit/
│   │   │   │           └── contract/         # tests the public package
│   │   │   ├── workflows/                   # named thin multi-capability orchestration
│   │   │   ├── adapters/
│   │   │   │   └── <capability>/<provider>/ # concrete bindings to owned ports
│   │   │   ├── transport/
│   │   │   │   ├── http/v1/                 # FastAPI/OpenAPI mapping
│   │   │   │   └── cli/                     # backend-owned operational interface
│   │   │   ├── compatibility/
│   │   │   │   └── issue_<number>/          # temporary backend adapter code only
│   │   │   ├── operational_control_plane/   # launch state; no business tables
│   │   │   └── composition/
│   │   │       └── root.py                   # the only implementation wiring point
│   │   └── tests/
│   │       ├── architecture/
│   │       └── integration/                  # cross-module public-seam tests
│   └── web/                                  # independently buildable Next.js app
│       ├── package.json
│       ├── next.config.ts
│       ├── README.md
│       ├── app/                              # routes, layouts, journey composition
│       ├── features/
│       │   └── <feature>/
│       │       ├── module.json               # feature ownership definition
│       │       ├── MODULE.md
│       │       ├── index.ts                  # sole feature-to-feature import path
│       │       ├── components/
│       │       ├── forms/
│       │       ├── transport/                # generated client → view model
│       │       ├── view-models/
│       │       └── tests/
│       ├── journeys/                         # annual workspace/operator composition
│       ├── shared/                           # closed allowlist; never business policy
│       │   ├── design-system/
│       │   ├── accessibility/
│       │   ├── routing/
│       │   ├── i18n/
│       │   ├── display-formatting/
│       │   ├── telemetry/
│       │   ├── session/
│       │   └── transport/
│       ├── compatibility/
│       │   └── issue-<number>/               # temporary web adapter code only
│       └── tests/
│           ├── architecture/
│           └── e2e/
├── contracts/
│   ├── architecture/
│   │   └── module.schema.json                # copied from approved prototype
│   └── openapi/
│       └── talli-v1.json                     # canonical deterministic contract
├── packages/
│   └── talli-api-client/                     # committed generated TypeScript client
│       ├── package.json
│       └── src/generated/                     # never hand edited
├── compatibility/
│   ├── registry.json                         # CI allowlist and expiry metadata
│   └── README.md                             # no production code here
├── infra/                                    # deployment composition, no business policy
│   ├── database/                             # root runner; module migrations stay local
│   ├── web/
│   ├── backend/
│   ├── supabase/
│   └── observability/                        # vendor-neutral configuration
├── tests/
│   ├── contract/                             # HTTP/OpenAPI/provider-port boundaries
│   ├── compatibility/                        # old/new overlap while explicitly active
│   └── release/                              # customer-ready highest acceptance seam
├── docs/
│   ├── adr/
│   ├── agents/
│   ├── architecture/
│   └── prototypes/                           # disposable decision artifacts like this
├── graphify-out/                             # expected Graphify fast-path location
│   ├── GRAPH_REPORT.md                       # committed
│   ├── graph.json                            # committed
│   ├── .graphify_labels.json                 # committed, keeps community names stable
│   ├── manifest.json                         # generated locally; ignored (absolute paths)
│   ├── graph.html                            # generated locally, optional release artifact
│   └── cache/                                # ignored
└── scripts/                                  # named repository operations; no business rules
```

## Public entry-point convention

Backend consumers import only:

```python
from talli_backend.modules.ledger.public import LedgerCommands, LedgerQueries
```

`public/__init__.py` uses an explicit `__all__`. Imports from a capability's
`domain`, `application`, `ports`, `persistence`, `migrations`, or submodules
under `public` are forbidden outside that capability. Public types depend only
on the standard library and `shared_kernel`.

Web features import only:

```typescript
import { LedgerEntryList } from "@/features/ledger";
```

`index.ts` explicitly exports the feature surface. Deep feature imports are
forbidden. Business transport uses only `@talli/talli-api-client` through the
feature's transport module.

## Manifest convention

Every backend capability and presented web feature has `module.json`, conforming
to one versioned JSON Schema. JSON is recommended because Python, Node, CI, and
Graphify can parse it without choosing another runtime-specific format.

The manifest is the enforceable source of truth. `MODULE.md` explains intent.
Both must change together when ownership or the public interface changes.
A common scoped document template is provided in `MODULE.template.md`.

The manifest records:

- stable kind, name, path, owner, purpose, and documentation path;
- the sole public entry point;
- exports or owned routes;
- owned data and migrations for backend capabilities;
- consumed OpenAPI operation IDs for web features;
- typed dependency edges;
- ports and concrete adapter bindings;
- cache and direct-browser-flow policy for web features;
- forbidden responsibilities;
- colocated test locations; and
- referenced compatibility exceptions.

## Compatibility convention

`compatibility/registry.json` is the only exception allowlist. Each entry must
name:

- owning application and accountable owner;
- creation issue and removal issue;
- exact code paths and architecture rule suppressed;
- reason and expiry condition/date;
- stable-release overlap being protected; and
- status.

The code itself sits visibly in the affected application's `compatibility/`
area. New features cannot import it. Expired entries fail CI. The next capability
migration remains blocked until active entries are removed unless a human
records an explicit exception.

## Infrastructure ownership

`infra/` composes deployment and repository-level operations. It owns no domain
rules, authorization decisions, business tables, or provider semantics.

- Capability modules own their same-named Postgres schemas and migrations.
- The database root runner only orders module migrations.
- Backend adapters own provider-specific mechanics but bind to
  capability-owned ports.
- Next.js owns no business persistence credentials or migrations.
- OpenTelemetry-compatible configuration stays provider-neutral until a
  separately approved infrastructure decision.

## Test placement

- Backend behavior: capability-local `tests/unit`.
- Backend public interface: capability-local `tests/contract`.
- Web presentation: feature-local `tests`.
- Named cross-capability workflows: `apps/backend/tests/integration`.
- Import, manifest, ownership, and acyclicity rules: app-local
  `tests/architecture`.
- OpenAPI and provider-port contracts: root `tests/contract`.
- Temporary old/new equivalence: root `tests/compatibility`.
- Browser journeys: `apps/web/tests/e2e`.
- Final release verdict: root `tests/release`, preserving the customer-ready
  release gate.
