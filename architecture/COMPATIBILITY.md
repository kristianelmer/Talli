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

The active registry is a deletion-proven subset of the immutable baseline. The
current capability may remove its frozen scopes. A future record may shrink or
disappear only when every removed scope names a resource that the database
catalog assigns to the active capability. In both cases the checker requires
current source to prove that the exact path/rule/resource/operation finding no
longer exists. A lingering call, ambiguous operation, unavailable source,
unowned or differently-owned future resource, added scope, or new writer fails
closed. The checker also rejects changed ownership or removal mapping, a second
legacy runtime, and an exit review while a current facade remains. While the
one-time foundation recovery is pending, no shrink is allowed at all.

A proven deletion may change the frozen source digest only for its exact
enclosing path and operation. In that operation every retained frozen resource
must keep its exact occurrence count and no new persistence resource may appear;
every unrelated retained operation must keep both its exact frozen digest and
occurrence count. This is the strongest language-independent structural proof:
the checker cannot infer that changed control flow or helper calls are
semantically behavior-preserving. Characterization, contract, runtime, and
browser evidence owned by the active migration ticket prove that separately.

Legacy facades have no date-based expiry. Their hard expiry is the capability
stage named by their removal issue.

## Ledger #139 atomic-coordinator relocation

The owner decision in
[#139 comment 5434908084](https://github.com/kristianelmer/Talli/issues/139#issuecomment-5434908084)
adds one deletion-only exception to the resource-owner rule above. It is active
only when `ledger` / #139 is the current migration stage. It covers the four web
operations `recordAdminCost`, `recordDividendReceived`,
`recordShareholderLoan`, and `recordTaxSettlement`, and the five future posting
routines `accept_bank_transaction_suggestion`, `record_share_purchase_fifo`,
`record_share_sale_fifo`, `finalize_corporate_decision`, and
`record_owner_dividend_payment`.

The checker pins the 24 registered scopes for the seven affected web operations
to their exact frozen record, path, rule, resource, and operation. A relocation
attempt must delete every frozen scope for that operation together. A partial
deletion, a different stage or issue, a new operation or resource, a changed
retained occurrence, or any tuple outside the whitelist fails closed. The
baseline file and digest remain immutable. `finalizeCorporateDecision` and
`recordOwnerDividendPayment` had no registered baseline scopes; their two named
SQL routines are nevertheless inside the owner-approved implementation and
contract-test boundary and may not remain browser-callable after cutover.

The relocated code may only coordinate the frozen future-owned writes and the
ledger public contract in one request-bound Postgres transaction. It may not
move future policy or ownership. Option A preserves only the audit continuations
already characterized as idempotent and after-commit; retry reconciles the exact
immutable audit row without repeating a committed business transaction, and an
audit failure cannot be reported as success. Audit already inside a frozen
future routine stays in its existing transaction. This exception does not move
audit persistence into or out of a transaction and does not broaden policy,
schema, provider, contract, capability, error, idempotency, retry, or
risk-response behavior.

## #200 case-bound support security amendment

The owner approval in
[#200 comment 5467952439](https://github.com/kristianelmer/Talli/issues/200#issuecomment-5467952439)
adds one deletion-only exception while the serialized pointer is investments or
later. It applies only to `apps/web/app/lib/supabase/server.ts`, operation
`searchOperatorSupportDashboard`, rule `direct-web-business-persistence`, and
these six exact record/resource tuples:

- `compat-billing-persistence`: `table:billing_accounts` and
  `table:billing_payment_events`
- `compat-annual-compliance-persistence`:
  `table:filing_readiness_snapshots`
- `compat-rf1086-persistence`: `table:authority_permissions` and
  `table:filing_submissions`
- `compat-audit-persistence`: `table:audit_events`

All six must disappear together. The immutable baseline remains byte-identical;
the checker bypasses only the future-resource-owner timing check for these exact
deletions. Current-source deletion, no-added-writer, frozen occurrence, baseline
digest, stage serialization, and completed-gate checks remain mandatory. A
partial deletion, different path/rule/resource/operation, pre-investments stage,
retained browser call, or added persistence fails closed.

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
3. Keep every retained future operation byte-for-byte frozen unless the same
   operation has a source-proven deletion of a resource catalog-owned by the
   active capability. Preserve every future-owned persistence call and count;
   never add a scope or writer. Do not migrate another capability concurrently.
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

The #152 owner actions now route Tax overrides, review comments, acknowledgements,
permissions and manual evidence through the declared generated API. The exact
seven operation digests (five owner actions plus readiness refresh and Archive)
are pinned in `TAX_RETURN_COMPOSITION_DIGESTS`. This is a
Tax migration within the existing mixed functions: every retained Accounts and
Audit persistence chain, original tuple and occurrence count remains unchanged.
The composition is admitted only at #152 or after Tax has exited, and only after
the original Tax import facade is removed. Dynamic resources, additional writes,
altered retained chains, or any different operation body still fail the guard.
The two source compositions add a complete owned Tax read; they stop when it is
unavailable. Archive includes only evidence referenced by selected-year Tax
submissions. The #146 composition pins remain unchanged and cannot authorize
these #152 bodies at an earlier stage.
The frozen #185 baseline and #151 twelve-tuple attribution are unchanged.
