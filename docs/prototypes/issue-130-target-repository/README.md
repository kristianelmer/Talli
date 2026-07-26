# Issue #130 target-repository prototype

> **DISPOSABLE DECISION ARTIFACT — NOT PRODUCTION ARCHITECTURE**

This prototype answers GitHub issue #130. It makes the proposed repository tree
and module-definition format concrete enough to review before any production
code is moved.

It does **not** reorganize production code, implement FastAPI, change the
Next.js application, alter persistence, or select infrastructure.

## Recommendation

Use:

- two independently buildable applications under `apps/web` and
  `apps/backend`;
- one JSON manifest format, validated by one versioned JSON Schema, for backend
  capabilities and web features;
- exactly one public entry point per backend capability and web feature;
- capability-local backend domain, application, ports, persistence, migrations,
  documentation, and tests;
- capability-owned provider adapters at the backend edge;
- route-only composition in `apps/web/app` and presentation code in
  `apps/web/features`;
- committed OpenAPI and generated-client artifacts outside either application;
- visible, expiring compatibility registries and app-local compatibility code;
- a single backend composition root;
- root-level `infra/` that owns deployment composition but no business data or
  policy; and
- root-level `graphify-out/`, preserving Graphify's fast-path convention while
  committing only durable architecture outputs.

The concrete proposal is in [TARGET_TREE.md](TARGET_TREE.md). The schema and two
filled examples are intentionally small enough to inspect:

- `module.schema.json`
- `MODULE.template.md`
- `examples/backend-ledger/module.json`
- `examples/backend-ledger/MODULE.md`
- `examples/web-ledger/module.json`
- `examples/web-ledger/MODULE.md`

## Live review

From the repository root:

```bash
python3 docs/prototypes/issue-130-target-repository/review.py
```

The command validates the example manifests without third-party dependencies
and prints the proposed tree and manifest summaries. It reads files only.

## Decision boundary

If approved, the resolution belongs on issue #130 and a single compact pointer
belongs in issue #122. This prototype remains disposable. It is not an ADR and
does not change `CONTEXT.md`, because it assigns technical ownership without
changing Talli's product language.
