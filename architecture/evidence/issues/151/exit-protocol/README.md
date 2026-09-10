# RF-1086 deployment-order protocol proof

Result: **29 checks passed**, 33 real loopback HTTP API requests, Node exit 0. No application defect found in this bounded proof. This is protocol/coordinator evidence with existing local fakes, not persisted-runtime, database migration, browser hydration, live authority, identity-provider or complete stage-exit evidence.

## Immutable sources

- Exact predecessor: `91b178c281bcc5fb887a6257d2f72e380199f3e6`.
- Exact candidate: `dd1a7dba8192746f5e882d5b119d895bf7730ce1`.
- `run.py` verifies both commit IDs and uses `git archive` to extract original application, test fixtures, generated client, web transport, backend configuration and action sources. It does not use the checkout's mutable versions of these sources.
- `source-manifest.json` records SHA-256 for every extracted source and all three executable harness files. `results.json` also records hashes of the six exact action bodies executed.
- Actual old/current FastAPI applications and coordinators run in separate local processes; the existing corresponding `CoordinatorSession` fixtures inject authority, persistence, billing and identity data. All tokens and UUIDs are synthetic fixtures. The harness rejects non-loopback fetches and server-side outbound socket connections.

## Reproduce

Keep `run.py`, `server.py` and `proof.mjs` together. Supply a repository containing both commits and its existing development dependencies. Output must be under `/tmp` and outside the checkout. The harness only reads the repository and extracts sources into the output directory; its two temporary loopback servers are terminated in `finally`.

```sh
"$REPO/apps/backend/.venv/bin/python" -B /path/to/harness/run.py \
  --repo "$REPO" --output /tmp/talli-151-rollout-recheck
```

Omitting `--output` creates a fresh `/tmp/talli-151-rollout-protocol-*` directory. The proof uses installed FastAPI 0.116.1, uvicorn 0.35.0, pytest 8.4.1 and Node v25.6.1. TypeScript is loaded from the supplied repository's installed development dependency solely to transpile the exact action function bodies.

## Executed assertions

1. Predecessor transport/generated client against candidate real FastAPI, and candidate transport/generated client against predecessor real FastAPI: compatible Send and recovery request method, path and JSON body; bearer propagation; generated-client response validation; `no-store`; server-generated request identifier when the transport supplies none; explicit caller correlation identifier round-trip.
2. Send preserves fresh-MFA/token-before-begin ordering. A repeated successful Send reuses the same five in-memory journal operation IDs/body hashes/idempotency keys without additional authority fake calls. An unknown first POST followed by retry has one unknown journal entry, unchanged identity and exactly one authority fake mutation. A failed token gate and invalid bearer cannot begin a mutation. Recovery performs no authority mutation or begin.
3. All eleven current preparation wrapper cases hit an absent route on the exact predecessor and throw the current generated client's `TalliApiError(404)` with no owned `SHAREHOLDER_REGISTER_FILING_NOT_FOUND` code. The preview lookup and owned-comment acknowledgement therefore do not return null. There is exactly one request and no session, coordinator, journal or authority fake effect per case.
4. Six exact candidate action function bodies (override, review comment, acknowledgement, simulation, permission and test evidence) use the real current transport against predecessor HTTP. Each takes the error redirect, never the success path, and makes no public table read/write/audit call or revalidation. Boundary identity/form helpers are injected; permission/evidence step-up is a local stub. These are extracted action execution tests, not a hydrated Next application. The backend's missing-route response remains the actual predecessor response.

## Deployment interpretation and limits

Deploy the new backend before switching preparation clients; quiesce obsolete direct preparation writers before writer cutover; contract last. The new client's safe failure against an older backend is intentional. This proof does **not** promise uninterrupted obsolete preparation UI after SQL writer cutover. Its retained Send/recovery compatibility is an HTTP/application property with local fakes; persistent journal identity, overlap, writer barriers and contraction require the separate SQL lifecycle/gate evidence owned by the parent review. Those database checks were not run by this harness.

## Artifacts

- `transcript.log`: final complete passing console transcript.
- `results.json`: per-case requests, coordinator events, fake authority call names, operation snapshots, errors, redirects and action-body hashes.
- `source-manifest.json`: exact revisions, SHA-256 source bindings, harness hashes and installed Python dependency versions.
- `old-server.log`, `new-server.log`: local server logs (empty on the passing run).
- `run.py`, `server.py`, `proof.mjs`: complete reproducible executable harness.

The extracted source trees need not be committed; the preserved generator recreates them from the pinned commits.
