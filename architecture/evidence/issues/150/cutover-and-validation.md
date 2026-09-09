# Authority Connections cutover and validation

This records the local #150 implementation and its operational boundaries.
`requirements.json` remains the acceptance ledger; an incomplete or local result
does not complete #150 or authorize the next serialized stage.

## Ownership and application order

The expansion moves System User requests and authority-operation state to the
private `authority_connections` schema. Its old public names are overlap views,
not a second store. The final contract removes those views and their obsolete
authenticated functions/grants. Obligation-specific `authority_permissions` and
filing evidence remain with their source-owning filing stages under the approved
semantic disposition. Launch signoffs remain backend-system technical records.

Apply the numbered expansion migrations in order, including the exact RF
relocation after Authority Connections and launch-signoff expansion. Deploy the
backend contracts before switching the web to its generated client. The backend
verifies the Supabase bearer and uses the existing restricted
`TALLI_LEDGER_DATABASE_URL` login. The migrations grant that login only explicit
SET membership in the new executor roles, without inherited data authority.
The relocated RF coordinator retains the original RF tables and journal and
uses the published Billing, Company Access and Documents contracts.

The web server and backend share a dedicated
`TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY` of at least 32 random bytes. It proves the
cookie-bound callback transport; the backend still independently authenticates
the original owner and validates the original request. A missing key denies new
callback-producing requests. Provider private keys and delegation stay solely in
the backend; none of the four standalone command entrypoints is a web endpoint.

After verifying the complete backend/web slice during overlap, apply the
Authority Connections contract, followed by the launch-signoff contract. The
Authority contract rejects premature cutover before the RF routines use their
owned request/lock projections. Contract SQL preserves the Company Access and
Billing consumer seams instead of granting access to private tables.

All production authority flags remain disabled for local verification. This
change does not provision credentials, run real filings, activate provider tests
or promote production. A ready web deployment alone does not establish a
functioning backend or a successful owner journey.

## Rollback and recutover

Disable the successor application path before rolling back its storage seam.
Restore the Authority overlap contract if contracted, then roll back RF,
authority operations and Authority Connections, in that dependency order. The
single predecessor request store and its exact prior grants are restored;
the Billing verified-request projection remains available to its current owner.
The explicit grant ledger reverses only privileges borrowed by this expansion.
The separate launch-signoff rollback restores its prior technical writer.

Reconcile original intent IDs, counts and deterministic row hashes before
recutover. Apply Authority Connections, operations and RF expansion again, then
the two contracts. Never repeat an unknown external mutation as a migration
recovery step. `scripts/rehearse-authority-topology.mjs` implements the exact
local-only dependency sequence around the unchanged Billing lifecycle tests.
The database suites also exercise the individual rollback/recutover contracts.

## Local evidence and review scope

The mandatory database lane uses a disposable loopback Supabase stack. It runs
all predecessor consumers, their browser journey and Billing lifecycle, then
recuts and tests the contracted Authority/RF/launch topology. The successor
browser uses real authentication, backend workflows, SQL and Documents storage
with a bounded loopback authority fake. This proves application integration;
it is not new Altinn, Skatteetaten or Vipps conformance evidence.

Standalone command characterization compares exact request sequences, original
instance/UUID continuation, statutory bytes and hashes, environment/write gates,
safe errors and existing human handoffs. Independent reviewers reproduced five
relocation regressions: BOM decoding, blocking FIFO admission, numeric-year/null
ledger inputs, lone-surrogate hashing/evidence, and an unenforced subprocess
output cap. Their corrected regression suites pass locally. Tax/accounts retain
the source 20-second default deadline and gain explicit response bounds and
redirect refusal; the approved amendment records those narrow safeguards.

The two new immutable complete gates, whole-stage review, protected integration
and exact-main Release/Preview evidence are still required. The immutable entry
baseline is not either exit gate.
