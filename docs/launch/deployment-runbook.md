# Talli deployment runbook

Status: repeatable container build and smoke test; public launch and direct filing remain gated

## Artifact contract

The production image contains:

- the Next.js standalone server and static assets;
- the `holding_cli` and `holding_core` Python packages;
- the two RF-1086 XSD files used for validation;
- a locked Python virtual environment built from `uv.lock`.

The image does not contain local `.env` files, test files, repository evidence Markdown, Supabase migrations, or Python bytecode caches. `npm run build` sanitizes the standalone output and `npm run test:packaging` verifies this boundary.

The Node and uv images are pinned by multi-platform digest in `Dockerfile`. Python dependencies are installed with `uv sync --locked`, so the build fails instead of silently updating the lock.

## Build and smoke test

From the repository root:

```bash
npm run test:release
npm run test:container
```

The smoke test builds `talli:smoke`, starts it as the non-root `node` user with
a read-only root filesystem, all Linux capabilities dropped, and
`no-new-privileges`; verifies `/api/health` and `/api/ready`; imports the filing
runtime inside the image; and confirms that local environment files are absent.

For a release image, use an immutable source revision as the tag:

```bash
docker build --pull --tag registry.example/talli:<git-sha> .
docker push registry.example/talli:<git-sha>
```

Record the resulting image digest in the release evidence. Deploy by digest, not a mutable tag.

## Runtime configuration

Inject secrets at runtime from the deployment platform's secret manager. Do not pass them as Docker build arguments or copy an environment file into the image.

Required for application readiness:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`

The image supplies these bounded filing-runtime defaults:

- `TALLI_PYTHON_BIN=/app/.venv/bin/python`
- `TALLI_PYTHON_TIMEOUT_MS=30000`
- `TALLI_PYTHON_MAX_OUTPUT_BYTES=20000000`

There is deliberately no environment switch that turns the RF-1086 simulator
into a production adapter. Production mode fails closed in code until a real
authority adapter is implemented, its real responses and receipts are persisted,
and the RF-1086 authority, official test-submission, security, billing, and named
human release gates are complete. A deployable application image is not
permission to make a live filing.

Apply `supabase/migrations/0001_authenticated_workspace.sql` through the controlled Supabase migration workflow before routing customer traffic. Run the documented RLS/storage audit against the deployed schema and record its evidence separately.

## Operational probes

- `GET /api/health`: liveness; returns `200` while the web process can answer.
- `GET /api/ready`: readiness; returns `200` only when Supabase configuration, the executable Python runtime, and both RF-1086 schemas are present. It returns `503` with stable reason codes otherwise.

The container health check uses liveness. The deployment platform should use readiness to decide whether a new revision can receive traffic.

## Release sequence

1. Run type checking, Python tests, the launch rehearsal, production build, packaging test, and container smoke test.
2. Apply and verify the database migration in a non-production project, then in production under change control.
3. Inject runtime secrets and deploy the image by digest with one instance receiving no public traffic.
4. Confirm liveness, readiness, authentication, tenant isolation, signed document access, and audit recording.
5. Run the backup/restore and security signoff procedures and attach evidence.
6. Route limited traffic only after all public-launch gates pass.
7. Leave every live filing adapter disabled until its filing-specific release gate passes.

Rollback means routing traffic to the previous known-good image digest. Database changes require a separately reviewed forward-fix or rollback plan; do not infer schema rollback from application rollback.
