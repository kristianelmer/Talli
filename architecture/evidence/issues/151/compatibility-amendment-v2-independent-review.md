# Independent review of the exact #151 amendment revision 2

Observed 2026-09-09T21:22:33.820Z against working source at HEAD `3e8bf5187d614a3a2d02437f12186d90dbd19078`. Read-only proposal/source review; no repository changes, tests, database or provider operations.

**No actionable discrepancy found.** The revision is suitable for requesting a decision on sixteen exact dispositions. This review is not owner approval and does not certify the full migration or browser/gate completion.

## Exact scope and immutability

The additional inventory resolves to exactly one immutable baseline tuple: `compat-company-archive-persistence` / `company_archive` / `#157` / `apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts` / `direct-web-business-persistence` / `table:opening_balance_setups` / `GET`. The original proposal, exact scope document and 37-tuple adjacent-effect inventory are byte-identical to their committed checkpoint and match all three hashes bound by revision 2. Therefore the adjustment is the original twelve handoffs and three removals plus this one deletion; it does not silently modify the original fifteen. The immutable baseline hash also matches.

Using the existing checker’s exported `legacyOperationProof` without invoking the checker CLI reproduces original count **1**, current count **0**, and both claimed operation digests exactly. Independent TypeScript AST inspection of the full route finds no dynamic persistence target and no remaining opening-balance resource string. The replacement follows the generated year-scoped Ledger read to the previously authorized RF/Ledger composition; no moved direct web writer is introduced.

## Ownership and preserved effects

The historical archive selection includes `bank_balance` alongside share and opening identity fields. RF owns the latter and Ledger owns the bank amount. The current database-catalog schema and checker map each compatibility resource to one owner, reject duplicate aliases, and use that owner as deletion authority. Assigning this historical whole resource to either owner alone would overstate ownership. The proposal therefore names one alias-free retirement; it neither creates a general split-resource exception nor grants RF monetary authority. The independently wholly RF shareholder tuple remains governed by the ordinary owner exception.

All eight remaining generic archive `.from` chains are AST-identical to their original counterparts and remain exactly once: filing_submissions, authority_test_runs, filing_previews, holding_actions, authority_permissions, filing_review_comments, audit_events and bank_suggestion_acceptances. Both archive begin/complete RPC call expressions match the immutable source. Against #151 entry `7a49f010229baf13d4942364d352786d7cddc5c3`, the authorization/MFA/begin prefix and serialization/hash/receipt/HTTP-response suffix are AST-identical. Earlier authorized capability cutovers explain why the complete prefix is not compared wholesale to the older immutable foundation source.

The original eight adjacent action audit scopes still each have one occurrence, and queueDeadlineReminders retains both notification occurrences. Their preservation requirements and placements are unchanged by this revision. The new archive opening query selects the requested year before integrity/decoding; the proposal does not authorize changed archive fields, amount, identity, error or export behavior.

The stated SQL evidence is referenced only: `/tmp/talli-151-combined-runtime-run2.json` and `.log` record the existing 104-case local run with source hashes. I authored that SQL slice, so this proposal review does not recast those results as independent SQL certification. Full independent migration review, browser evidence, both immutable gates and protected integration remain required.

## Bound artifacts

| Artifact | SHA256 |
| --- | --- |
| `architecture/evidence/issues/151/compatibility-amendment-v2-proposal.md` | `37472588213825c948c4a4870e9df7396b10aa273e9d1c5118db929d9149b09a` |
| `architecture/evidence/issues/151/compatibility-amendment-v2-inventory.json` | `698439251dbba00606c04ea9599032db5f3a082a14946ad4cb1beef24d121c28` |
| `architecture/evidence/issues/151/opening-catalog-assessment.md` | `c337794eab75e7186a9dcafeb367f789a41e1b5c65f277ecf77dd0433569995f` |
| `apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts` | `c83ccf71c9eeb9a05316bed2b5a5fee387f36d478cafc08c201afa1bb6bf2373` |
| `scripts/check-architecture.mjs` | `1e3167d86cd9a9b9ed04e6df803e93bba1f749bc2f750ac0242e8041eab83031` |
| `docs/adr/0013-enforce-the-architecture-and-migrate-serially.md` | `e9c5a49e099776bed786104d0c361c951670c21a27d08eee5c1cb0f3c22716ba` |
| `architecture/database-catalog.json` | `336827088e88d2e2c0dc9ed18a237e8352bb68bb25866b06a5fa523d9c3a6822` |
| `architecture/database-catalog.schema.json` | `87565d2a446d140fdfb6fe42ad28f0e11c82596bf1dd48cc0589f4422ae7d52e` |
| Original `compatibility-amendment-proposal.md` | `3cc58e95162e6cd52328a075019419e1005f9ca8794eda1811b77fc30ae50d40` |
| Original `frozen-scope-disposition.md` | `af56cf7ad98bdf0feca6c4b2d9208545fc1c633d3f66596f3bf5dfa8ff950da3` |
| Original `frozen-scope-inventory.json` | `e0e8f9e2a3835ca206817f3b6d1a0529ce6340e1638b8c59b624f5aef2240f12` |
| `architecture/compatibility-baseline.json` | `b8731da45dbf69baafba4e1101dc9a86dcc4ccf11057ebc1fac9b4b059c819ab` |

Reproducible read-only details: `/tmp/talli-151-v2-independent-ast-proof.json` and `/tmp/talli-151-v2-independent-effects-proof.json`. Existing checker source was imported for its proof function only; no evidence writer or architecture mutation was called.
