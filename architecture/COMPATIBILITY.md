# Compatibility and serialized migration

`compatibility.json` is the machine-readable control for the one-capability-at-a-time
migration established by ADR-0013. It has two deliberately different record
kinds.

## Legacy facade

A `legacy-facade` records a direct web business-access seam that already existed
at frozen revision `d331ee2717d1eeacef0d81db42b9d4fb5848b408`. Its source record,
exact suppressible scopes, migration capability, removal issue, and canonical
legacy runtime are fixed in `compatibility-baseline.json`, whose canonical JSON
digest is pinned by `compatibility.json`. Each frozen scope also records the
source operation's SHA-256 and persistence-call count at that revision.

The current capability may only shrink its legacy scopes. A future capability
must match its frozen record exactly. A migrated capability may have no facade.
The checker rejects baseline additions, changed ownership, changed removal
mapping, scopes absent from the source revision, a second legacy runtime, and an
exit review while a current facade remains. Current-stage calls may not exceed
their source count; future-stage operation digests and counts must remain exact.

Legacy facades have no date-based expiry. Their hard expiry is the capability
stage named by their removal issue.

## Active-stage debt

An `active-stage-debt` is new, bounded debt created only by the active migration
stage. It identifies the current stage issue, one immediately succeeding
capability, residual risk, rollback, exact scopes, human approval, and removal
condition. It expires at the earlier of fourteen days after approval or the next
stable customer-ready release. It blocks the successor capability's exit and
cannot survive beyond that successor.

Active-stage debt is not a way to expand frozen future facades. Every scope is
still exact by source path, rule, resource, and enclosing operation.

## Non-suppressible failures

Only these temporary boundary findings can appear in either record kind:

- `direct-web-business-persistence`
- `direct-business-fetch`
- `generated-client-deep-import`

Authorization or RLS failures, unowned state, circular dependencies,
statutory-output differences, secret leakage, and ambiguous external effects
remain unconditional failures.

## Stage transition

1. Claim and activate only the next issue in `migration.order`.
2. Characterize the current legacy behavior, establish the canonical capability
   writer, migrate and reconcile, then delete obsolete scopes and code.
3. Keep every future legacy record byte-for-byte equivalent in meaning to its
   frozen baseline. Do not migrate another capability concurrently.
4. Set `status` to `exit-review`. The architecture check must reject the exit if
   a current facade or blocking predecessor debt remains.
5. Run the complete customer-ready gate on two distinct committed revisions.
6. Advance `currentCapability`, update `exitedCapabilities`, and add the exited
   capability to `completedStages` with its exact removal issues and both gate
   attestations. Each attestation is a committed, digest-pinned JSON record bound
   to its revision and the complete application/database check set. The second
   pass names the first as its previous passing revision.

Run the gate with `npm run gate:customer-ready`; pass the first passing commit to
the second run as `-- --previous <revision>`. The runner refuses a dirty tree and
writes a committed JSON attestation plus the complete command transcript. Each
attestation is bound to the runner source at the tested revision and pins both
the runner and transcript SHA-256 digests. The architecture checker independently
verifies those files, digests, successful check results, revision ancestry, and
the consecutive-pass link before accepting a recovery or stage exit.

`completedStages` must exactly equal the capabilities before the current stage;
this keeps the evidence requirement inseparable from every later architecture
check. The one-time `foundationRecovery` control applies the same attestation
rules to issue #186 before the first capability migration starts.
