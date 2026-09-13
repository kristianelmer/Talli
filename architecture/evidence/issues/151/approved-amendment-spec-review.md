# Independent Spec review and corrective recheck — #151, d060

Review performed by the delegated Spec reviewer, independently of implementation. Repository was read-only throughout; no database, browser, hosted service, provider or production operation was performed. This artifact records source review and narrowly executed checks, not full #151 acceptance.

## Pinned migration review

Fixed point: `91b178c281bcc5fb887a6257d2f72e380199f3e6`.
Pinned candidate: `8f86488cb32e8d50ad8546654e20ea46d9c8885d`.
Verified the fixed point resolves, `git diff 91b178c281bcc5fb887a6257d2f72e380199f3e6...8f86488cb32e8d50ad8546654e20ea46d9c8885d` is nonempty, and the five candidate commits are `7a49f010`, `3e8bf518`, `7730bd34`, `4081b410`, `8f86488c`.

Spec sources: the live #151 snapshot supplied at `/tmp/talli-151-live-d060.json`, `architecture/evidence/issues/151/requirements.json`, `source-contract-requirements.md`, `characterization-test-plan.md`, and `followup-verification.md`. The exact16 amendment was approved for implementation after the pinned candidate; its then-pending wiring was excluded from this first pass.

Inspected source contracts, readiness/history/completeness/currentness, preparation and production coordination, Ledger opening separation, and generated-wire presentation. Previously documented source-warning/outcome and other follow-up findings were reviewed as corrected, not reported anew. This review did not exhaustively prove every line of the large migration or substitute for the #132 exit envelope.

### Finding and correction: RF-owned authority readiness

**Original finding [P1]:** `source_facts.py` `_readiness` ignored `workspace.permissions`. A valid rendered preview yielded ready, complete and currently verified source evidence with no authority permission or with production disabled. This contradicted `source-contract-requirements.md:51` (RF-owned readiness and non-billing hard blocks, preserved rule semantics), compared with the retained `annual-readiness.ts:168–171` and `authority-permission.ts:51–72`. Actual Send authorization remained guarded; the defect was the source attestation.

Standalone reproduction: `/tmp/talli-151-source-permission-spec-review.py`. It uses the committed synthetic source fixture and actual `build_source_facts` / `verify_source_evidence`; it makes no adapter or database calls. The first execution used the existing original-worktree Python runtime with this checkout's explicit `PYTHONPATH`, because its own runtime was not yet ready. After correction it ran with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/backend/src:apps/backend/tests apps/backend/.venv/bin/python /tmp/talli-151-source-permission-spec-review.py
```

Original result for missing, disabled and enabled permission: `readiness=ready`, empty hard blocks, complete coverage and current=true.

Independent corrected result:

| Input | Readiness | Hard block | Coverage/currentness |
| --- | --- | --- | --- |
| Missing permission | blocked | missing_authority_confirmation | complete / true |
| Confirmed, disabled permission | blocked | production_disabled | complete / true |
| Confirmed, enabled permission | ready | none | complete / true |

**Closed.** Currentness verifies the preserved evidence, including its blocked decision; it is not itself a claim of ready status. The implementation author's broader source-test counts are not claimed as independently rerun here.

## Review of the approved mixed-flow amendment

Reviewed the subsequent working-tree delta from `8f86488c` in `actions.ts`, `annual-workspace-server.ts`, `workspace-data.ts`, the new `rf1086-workspace-source.ts`, and RF transport against `frozen-scope-disposition.md` and the approved finite amendment.

### Finding and correction: canonical overlap routing

**Original finding [P1]:** override/review/acknowledgement actions initially selected the legacy writer whenever the generic lookup returned a row. Supported canonical overlap retains and mirrors RF public rows (`20260909190905_shareholder_register_filing_cutover.sql:90–108`), while its guard rejects public RF writes (`20260909190548_shareholder_register_filing_capability.sql:704–708`). Thus a visible RF mirror selected a retired writer; the initial merged read arrays also duplicated mirrors. This finding was traced through source, not reproduced against the database.

Correction independently inspected: canonical RF lookup/acknowledgement precedes legacy access. Only HTTP404 with exact `SHAREHOLDER_REGISTER_FILING_NOT_FOUND` permits fallback. Forbidden, unavailable and unrelated404 responses cannot select a legacy writer. `composeFilingSources` gives canonical IDs precedence and retains sibling rows; reminder and permission projections use their existing natural identities when ID is absent from the frozen select.

**Closed for the inspected correction.** This does not claim a full real-database overlap/browser deployment rehearsal.

### Finding and correction: shared owner-page availability

**Original finding [P2]:** the initial uncaught new RF load in `workspace-data.ts` bypassed its existing `productionStateError` recovery. RF API failure therefore rejected the shared loader used by dashboard, onboarding, documents, transactions, actions, year-end and filing. The annual route also bypassed its existing failed-source handling.

Correction independently inspected: RF helper catches transport failure and returns sanitized error plus empty affected collections. Shared workspace returns that error through its existing error channel, and annual reporting includes RF in `failedSources`. No failed source is claimed as a successful readiness/history attestation.

**Closed.** An independent in-memory extraction/transpilation of the actual helper functions was executed with a throwing RF source: it verified sanitized error, empty affected collections, sibling retention and canonical mirror preference. The extraction did not import a second implementation or write repository files.

## Independently executed correction checks

```sh
node --test tests/rf1086_mixed_actions.test.mjs apps/web/tests/shareholder-register-filing-transport.test.mjs
```

Observed **40 tests passed, 0 failed, 0 skipped, 0 cancelled**. These comprise14 extracted actual-action checks and26 real transport/presentation checks. Action dependencies are controlled test doubles; transport checks exercise the shipped generated client with deterministic responses. They cover canonical routing despite mirrors, fail-closed routing, exact typed-not-found fallback, retained sibling validator/write/audit sequence, simulation delegation, and RF/sibling step-up/audit placement. They are not database/browser proof. The helper extraction described above passed separately.

No additional actionable defect was found in this corrective slice. Original adjacent audit and notification placement and sibling validator/write order remain preserved in inspected source. This does not certify all possible failure branches or the full owner journey.

## Current source binding

The SHA256 values below were captured when writing this artifact; they bind the reviewed corrective state, not an immutable complete gate. Earlier executed results are described above; no repository write was performed by the reviewer.

| Path | SHA256 |
| --- | --- |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/source_facts.py` | `97df7a594b80e5c266926f88d98c65db18817575061d8590bf4d142f89ebd85b` |
| `apps/backend/tests/test_rf1086_source_facts.py` | `4d0c31a460b56bfe48954a19a2d97670cfcab5da1ec0705440fbc29288e475d3` |
| `apps/web/app/actions.ts` | `b407f01296b42bb7cc9f5c5e2e2633dcf97110618a818a84ced38270daa8e4f9` |
| `apps/web/app/lib/rf1086-workspace-source.ts` | `1c0c19d2635a69be66c54221a9013a35d16a996f0815f3350188cc67fa37a7ad` |
| `apps/web/app/lib/workspace-data.ts` | `15f9bace0dc494e4fe3b5e99f941de6602b00a4416e57073c4265df3f8650e73` |
| `apps/web/app/lib/annual-workspace-server.ts` | `47ca6b8fa90744680ecbc81b93b917ec2752720eca83aa11cebc095629aebb47` |
| `apps/web/features/shareholder-register-filing/transport.ts` | `72fb52f9b7026b37c7559a00af78d79b83daafed332a2cb97a0fbc1896a9f019` |
| `apps/web/tests/shareholder-register-filing-transport.test.mjs` | `1f85c4ba6e0a65e94f3295d2a1619d15e29d29e7e6ee3a13bf05ff9bea622fbe` |
| `tests/rf1086_mixed_actions.test.mjs` | `28277fcb912559e0ae2c3700bc40991253a2891a1a94c0dbb540ac66fd0d06d2` |

## Limits and remaining acceptance

No claim of full stage completion, #192 completion, complete #132 envelope, independent database correctness, fresh owner browser acceptance, both immutable complete gates, protected integration, exact-main Release/Preview, provider acceptance or production activation is made. Those require their own current authoritative evidence. The serialized source order and production freeze remain applicable. Known pending gates are not recast as code findings. This artifact closes the three specific findings above and records the tested scope honestly.
