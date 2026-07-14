# Corporate Document Local Rehearsal Evidence

Status: local automated and visual rehearsal passed; production release remains blocked
Run date: 2026-07-14
Recorded at: 2026-07-14T07:55:57Z
Code-under-test: `aa3afaf5bd3bd7e100e108b74e2a8eb03354fd4c`
Feature flag: `TALLI_CORPORATE_DOCUMENTS_ENABLED=false`

This evidence covers the local corporate-document implementation. It is not a
Norwegian legal/accounting approval, deployed Supabase security test, production
restore, or authority submission test. Every external release gate remains
pending in `docs/launch/corporate-document-release-gate.md`.

## Environment

| Component | Version or reference |
| --- | --- |
| macOS | 26.5.1 |
| Node.js | v25.6.1 |
| npm | 11.9.0 |
| Python | 3.12.11 through `uv` |
| uv | 0.10.2 |
| ReportLab | 5.0.0 |
| Poppler | 26.04.0 |
| Docker | 28.4.0 |
| Fresh database | `postgres:16-alpine` disposable container |
| Next.js | 16.2.9 |
| Template version | `corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1` |

Pinned font hashes:

| Font | SHA-256 |
| --- | --- |
| `holding_core/assets/fonts/NotoSans-Regular.ttf` | `b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5` |
| `holding_core/assets/fonts/NotoSans-Bold.ttf` | `c976e4b1b99edc88775377fcc21692ca4bfa46b6d6ca6522bfda505b28ff9d6a` |

## Static Safety Review

The legacy-placeholder scan found no `Styreforslag utbytte.txt`,
`Generalforsamlingsprotokoll utbytte.txt`, or `missing_placeholder` references.
`Dividend paid from bank` exists only as a negative assertion in
`tests/owner_dividend.test.mjs`. Account `1920` matches are legitimate bank
postings in other workflows and fixtures; corporate declaration accounting is
derived from the reviewed policy and does not post bank payment at declaration.

The secret-material scan found only identifier names or synthetic values in
tests and documentation (`service_role`, `SUPABASE_SERVICE_ROLE_KEY`). It found
no embedded service-role value and no PEM/private-key block in `app`,
`holding_core`, `tests`, or non-plan documentation.

## Automated Verification

| Command | Result |
| --- | --- |
| `uv run python -m unittest discover -s tests -p 'test_*.py'` | Passed: 68 tests, 0 failures |
| `npm run test:launch-rehearsal` | Passed: every chained suite exited 0 |
| `npm run test:corporate-documents` | Passed: 20 tests, including fresh PostgreSQL rehearsal |
| `npm run test:corporate-decision-workflow` | Passed: 4 tests |
| `npm run test:owner-dividend-payment` | Passed: 4 tests |
| `npm run test:web` | Passed: 4 tests |
| `npm run test:supabase` | Not exercised against a deployed project: 1 test skipped because Supabase URL/keys or usable `DATABASE_URL` were absent |
| `npm run typecheck` | Passed |
| `npm run build` | Passed: production build and route generation completed |
| `npm audit --audit-level=high` | Passed: 0 vulnerabilities |
| `git diff --check` | Passed before the implementation commit; repeated in final handoff checks |

The company-tax-return XML suite contained one intentional skip because the
pinned official XSD bundle was not supplied. This is an authority/schema gate,
not a corporate-PDF failure, and it is not counted as passed.

## Fresh PostgreSQL Rehearsal

`tests/corporate_document_database_runtime.test.mjs` applied migrations
`0001`–`0004` to a disposable PostgreSQL 16 container and executed
`tests/fixtures/corporate_documents/database_rehearsal.sql`.

The passing rehearsal covered:

- draft creation and exact idempotent retry;
- rejection of forged financial totals even when the attacker supplies the
  matching recomputed canonical decision hash;
- database recomputation of the canonical hash, ledger totals, company facts,
  shareholders, represented shares, votes, confirmations, dates, liquidity,
  annual allocation, and exact largest-remainder dividend allocation;
- facts approval, signing request, owner-attested signed copies, signer
  requirements, and rejection/supersession terminal states;
- denial when the persisted annual ledger changes after approval;
- denial of owner-dividend finalization and payment in a locked period;
- exactly one enabled reviewed accounting policy;
- declaration posting to the policy debit/payable accounts without bank
  payment, followed by partial/full matched payment and no overpayment;
- direct-record immutability, cross-company source denial, and internal helper
  execute privileges revoked from `authenticated`; and
- annual-close finalization without an owner-dividend ledger/action side effect.

This is local database evidence. It does not replace the pending authenticated
RLS/private-storage rehearsal against the target Supabase project.

## Private Storage Orchestration

The local storage tests passed for:

- company/year/set/kind-scoped content-addressed keys;
- path-injection rejection;
- `upsert:false` immutable upload behavior;
- exact existing-object byte/hash verification on retry;
- failure on a same-key/different-content object; and
- cleanup of only objects created by the current failed attempt.

No target Supabase credentials were configured. Owner/member/cross-tenant RLS
and real private-object behavior in the deployed project remain pending.

## Deterministic PDF Evidence

Both fixtures were rendered twice through
`uv run talli render-corporate-documents --stdin-json`. Each corresponding byte
stream compared equal with `cmp`. `pdfinfo` reported one unencrypted A4 page,
PDF 1.4, for every artifact. Metadata creation/modification timestamps are fixed
to 2000-01-01 rather than the render time. `pdftotext -layout` extracted the
company name, spaced organization number, Norwegian names/characters, meeting
facts, decision text, amounts, signature labels, template version, and decision
hash from all four PDFs.

| Artifact | Decision SHA-256 | PDF SHA-256 | Bytes | Pages |
| --- | --- | --- | ---: | ---: |
| Annual board minutes | `930a5994ae835c093716e3f97b71c4184731f999721dbc08e9057536498688ce` | `ca3347d5143c51f361d3b0244990c611ff5cba99fbdd70273a30f44ba89cf7c2` | 32,068 | 1 |
| Annual general-meeting minutes | `930a5994ae835c093716e3f97b71c4184731f999721dbc08e9057536498688ce` | `537cf696f6a3e9a6d951cf5fdf9a95f38eabef86333529a58f4580e142393204` | 32,627 | 1 |
| Dividend board proposal | `011d1f6df34bf979ee043f7466236aea727198b8b7606968ecf0fc761107366b` | `e6070d08a3293e50f595943cff41b7c9a6901828cea86430c4a62aed5ed5551a` | 32,120 | 1 |
| Dividend general-meeting minutes | `011d1f6df34bf979ee043f7466236aea727198b8b7606968ecf0fc761107366b` | `e46d9f7d4ef04a0dd4317002e6b999bd39e1f454351febffb13d7ccd87d46bef` | 32,385 | 1 |

## Visual Inspection

All four pages were rendered at 144 DPI with `pdftoppm` and inspected. The
review confirmed:

- complete, unclipped titles, identity, meeting tables, decision paragraphs,
  allocation tables, signature blocks, template version, and decision hash;
- no overlap, hidden content, extra page, or dynamic timestamp;
- correct Norwegian characters (`Å`, `Ø`, `ø`, `æ`) and readable monetary/date
  formatting; and
- consistent one-page A4 layout with sufficient bottom margin.

The in-tool PNG preview decoder initially displayed black bands on the dividend
general-meeting screenshot. This was isolated to that decoder: Pillow/macOS
decoded the same `pdftoppm` pixel file without filled regions, and independent
`pdftocairo` plus macOS Quick Look renders were clean. The exact `pdftoppm`
screenshots were re-encoded to JPEG for the visual review.

Reproducible temporary screenshot hashes from this run:

| Page screenshot | SHA-256 |
| --- | --- |
| Annual board minutes | `4edf20149287c86bcb1835eb368d4b2bda61ba506705c3f1065cd6a5bda07d1b` |
| Annual general-meeting minutes | `ea18fa9f7565eeaccbce978511807033dae1843ca657cc4b2a44e98fb8292129` |
| Dividend board proposal | `476fdcc16731e91b2c563618675bf3865440acd7f525583477eff205a2293fb8` |
| Dividend general-meeting minutes | `89b3bc9380a6f83b2e170a715d9da3b9ab9a16cb81595608189f8c25beaa0fec` |

These local screenshots are reproducible from the fixtures and are not legal or
product golden approvals. Named reviewers must regenerate or retain the
approved copies in immutable release evidence.

## External Gates Still Pending

| Gate | Status after this rehearsal |
| --- | --- |
| Norwegian corporate-law review of all four templates | Pending |
| Norwegian accounting review and enabled policy evidence | Pending |
| Named product/legal PDF golden approval | Pending |
| Target Supabase authenticated RLS/private-storage test | Pending |
| Isolated deployed backup/restore rehearsal no older than 30 days | Pending |
| Named legal/product review of corporate workflow copy | Pending |

Release conclusion: the implementation is locally reviewable and the automated
rehearsal is green, but production enablement is not authorized. Keep
`TALLI_CORPORATE_DOCUMENTS_ENABLED=false` until every row above is approved and
linked from the release gate.
