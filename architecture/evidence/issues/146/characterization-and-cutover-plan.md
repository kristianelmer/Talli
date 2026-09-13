# #146 entry characterization and cutover plan

Entry plan adopted at `20999f167084492bb4f9a5a50d0cbcd3a48333b3` after the complete immutable entry gate passed; independent review and claim remain pending. Original six criteria are authoritative. This is Company Tax slice1, not full Company Tax exit (#152).

## Characterization to preserve

- Payable, payment and refund capture; positive amount, old rounding/precision behavior, date/year, valid kind/document status, payable cannot link bank. Original coded Norwegian validation messages and API/RLS failures, ordering/defaults, stable operation IDs.
- Ledger public PostTaxSettlementCommand remains sole posting rule/writer, matching existing8300/2500,2500/1920,1920/1570 lines and Norwegian descriptions. Preview should reuse the Ledger-owned mapping through a public contract, not clone accounts into Tax.
- Same-company/year document and bank bindings, exact signed bank amount, no already-matched or accepted-warning bank. Bank match identity currently original action UUID, no added prefix. Preserve original date behavior (bankdate is independent; date/year guards remain).
- Original ledger workflow request metadata/fingerprint, actor/company/year/idempotency/operation identity and replay result. Technical receipts remain an explicit backend-system concern; do not assume receipt rows must move merely because the existing infrastructure name includes Ledger. No blind retry of unknown posting or bank effects.
- After-commit Audit continuation remains in its original placement with deterministic operation identity. Posting success plus unconfirmed audit must retain the same operation ID and explicit safe message, never reported as whole success or reposted.
- Wizard and workspace forms, async authoritative preview, blank/invalid/race states, Norwegian labels, successful posting display and stable retry operation ID. Existing tax history is derived from Ledger entries. Future annual-tax estimate and Company Tax filing calculation/evidence remain unchanged for #152.

## Storage and consumers

Current canonical predecessor writer is backend_system.prepare_tax_settlement_v1/complete_tax_settlement_v1 from20260827100500_ledger_writer_coordinators.sql through LedgerApplication and SupabaseLedgerTransaction. It writes public.holding_actions tax_settlement rows; Ledger/Banks are already canonical other owners. Full original row fields: id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at.

Investment stage exit removes share_purchase/share_sale/dividend_received and narrows the table constraint to dividend_to_owner/shareholder_loan/tax_settlement. Governance contract removes the remaining governance rows and its old writers. Therefore Tax is the remaining current writer, but the constraint still admits the two old governance labels. Never infer actual hosted row contents: any resource-ownership contraction must explicitly reject unexpected non-Tax survivors, verify predecessor reconciliation, and preserve them on failure. Do not acquire sibling data or invent a general mixed-resource exception.

Archive still has one exact year-scoped holding_actions read under #157 and combines canonical investment/governance projections separately. Preserve exact output, sorting, begin/complete/audit and generation tracking. If retiring this now-exclusive predecessor resource under ADR0013 resource-owner authority, prove actual ownership through catalog plus explicit no-sibling contract checks; do not mislabel a mixed resource. Keep immutable baseline and unrelated frozen tuples/counts unchanged. Documents retention helper still checks public.holding_actions; rebind through a source-owned reference seam without weakening removal protection. Preserve opaque Ledger/Banking/Documents IDs and current physical FK semantics. The current bank FK is to banking.transactions ON DELETE RESTRICT; Ledger FK was deliberately removed at Ledger contract.

## Required release proof

1. Pin actual entry main and all source/test/schema/rollback files; complete immutable11-check entry gate and independently verify committed receipt before claim.
2. Frozen-input characterization before replacement: all three settlement kinds, invalid/duplicate/unauthorized/locked-year requests, exact rows/entries/bank links/audit, preview and Norwegian journey. Permanent canonical tests retain assertions; remove temporary cross-language harness at exit and keep its evidence.
3. Expand/backfill then cutover then contract as separate shipped phases. Counts, original JSON hashes, identifiers/times and opaque references reconcile; no dual writer. Test deliberately malformed and unexpected sibling rows fail atomically.
4. Rehearse deployment orders using exact old/new app/transport/schema phases, fail unavailable safely where new endpoints/schema are absent. Repeated/ambiguous operations retain identity and never post twice.
5. Both rollback forms preserve/quarantine new state and original source evidence, restore one writer at the matching application/schema phase, reject conflicting/malformed quarantine, and support recutover without duplicate Ledger/Banking/audit effects or archive-generation side effects.
6. Real isolated PostgreSQL/RLS and authenticated FastAPI tests, pooled actor leakage/tenant concealment, no service-role ordinary path, repeated/concurrent/partial-failure bank+Ledger+Tax transaction coverage and Documents retention checks.
7. Generated-contract reproducibility; complete hydrated wizard/workspace journey, unknown outcomes/audit continuation; both builds, architecture/catalog/manifest/dependency/forbidden-web checks; independent Spec/Standards reviews and immutable gates/protected integration appropriate to the original stage envelope. #146 completion does not assert Company Tax stage exit until #152.

No hosted schema changes, real filing, provider activation, production promotion or paid services are authorized here. Production stays release/production atd331ee2717d1eeacef0d81db42b9d4fb5848b408.

## Exact replay ordering discovered at entry

`claim_ledger_writer_v1` hashes the complete PostgreSQL JSONB request text, including correlationId. The web deliberately passes the same operation ID as both Idempotency-Key and request ID. Preserve that exact serialization/identity contract; do not silently exclude correlation or change decimal strings. Accepted membership and ownership precede receipt replay; year-admission and period-lock checks follow successful claim only when no receipt exists. Historical exact replay therefore need not reopen a closed posting period or revalidate a now-matched bank.

The predecessor also returns an existing same-company tax action by action ID after the year lock even when no workflow receipt exists for the supplied key. That branch checks company/type but not every requested payload field. Characterize this separately before deciding how canonical historical replay/conflicting input behaves; do not conceal this difference or assume all duplicate branches enforce the same fingerprint. The original acceptance still requires invalid/duplicate requests to fail safely and no changed accounting outcome or duplicated effect.

## Stable HTTP contract constraint

ADR0012 requires approval/new-major treatment for breaking API changes. Preserve the existing `/api/v1/ledger/tax-settlements` path and `ledgerPostTaxSettlement` wire contract as the one canonical capture endpoint while replacing its internals with the Company Tax public workflow. A historical URL name is not permission to retain the old Ledger capture coordinator or duplicate writer. Move the web transport ownership to the Company Tax feature, retire the old Ledger capture/session/adapter implementation, and explicitly declare the workflow's Tax/Ledger/Banking/Documents public packages. New Tax preview/query endpoints can be additive. Verify exact old generated-client requests against the new implementation. If this cannot satisfy the actual public-contract rules, surface the concrete conflict rather than silently remove the released route or invent approval.
