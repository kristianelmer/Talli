# #146 tax-settlement entry inventory

Prepared against protected main `20999f167084492bb4f9a5a50d0cbcd3a48333b3` after #151 closed on 13 September 2026. The complete entry gate passed all eleven checks from 15:32:12.822Z to 15:52:13.794Z. Independent review and the serialized claim remain pending; no implementation is claimed. The source inventory binds 135 relevant source, contract, test, migration and rollback files to committed bytes at this revision.

## Slice and public contracts

#146 is Company Tax slice 1 of 2. It moves settlement capture, validation, persistence and owner presentation. Annual estimates, company-tax statutory calculation/XML/readiness/submission/evidence and full capability exit remain #152. Billing still owns commercial decisions; this slice adds no Billing writer.

| Entry or consumer | Current path and behavior |
|---|---|
| Owner wizard | `apps/web/app/(owner)/actions/_components/TaxSettlementWizard.tsx`: local validation/ledger preview, payable/payment/refund, stable operation UUID, Norwegian fields and submission action. |
| Workspace form and display | `apps/web/app/(owner)/workspace/page.tsx`; `workspace-data.ts` derives tax-settlement history from canonical Ledger entries, while annual estimates use the separate later-slice function. |
| Submission action | `apps/web/app/actions.ts:recordTaxSettlement`: current auth, form defaults, web validation, generated Ledger request, safe unknown-outcome redirect, deterministic after-commit Audit continuation, then revalidate/success. |
| Existing wire | `/api/v1/ledger/tax-settlements`, operation `ledgerPostTaxSettlement`, 201 `LedgerWriterResultWire`. Company/year, action UUID, date, Money/NOK, kind, document status and optional bank/document UUIDs. Strict body forbids caller-supplied lines. Preserve the released wire contract while moving its one canonical workflow internally. |
| Current backend workflow | `application/ledger_workflow.py:RecordTaxSettlementCommand` and `LedgerApplication.record_tax_settlement`; authenticated transaction prepare → Ledger public posting → complete, or original receipt/action replay. |
| Current persistence | `adapters/supabase_ledger.py:_writer_payload`, `prepare_tax_settlement`, `complete_tax_settlement`; exact original request JSON includes company/year/key/correlation/date/amount/kind/document and bank fields. |
| Ledger collaboration | `modules/ledger/public.py:PostTaxSettlementCommand` and `service.py:post_tax_settlement`. Ledger owns positive amount, canonical account selection, balanced lines, period/accounting policy and the only posting writer. Tax does not copy that implementation. |
| Banking collaboration | Canonical bank data is `banking.transactions`. Existing frozen SQL coordinates its compatibility relation; the new workflow must use Banking public contracts. Public external-action claim already exists; it validates the bank source date/hash/signed amount and match identity. |
| Documents | Document IDs are opaque references. Current full retention helper still queries `public.holding_actions`; preserve evidence protection through an owner-authorized reference query during cutover. Do not transfer blob or document lifecycle ownership. |
| Archive | `apps/web/app/archive/[companyId]/[incomeYear]/download/route.ts` has one year-scoped `holding_actions` read and separately composes canonical investment/governance output. Preserve original Tax row JSON, ordering, filenames, begin/complete/audit behavior and generation tracking. |
| Audit | `ledger-audit-side-effects.ts` uses framed deterministic UUID identity and verifies exact stored row after insert failure. Current placement is after business commit. A trace failure preserves the same operation UUID and cannot report complete success or repeat posting. |

## Storage and authority

`public.holding_actions` currently contains the predecessor row shape: `id`, `company_id`, `income_year`, `action_type`, `action_date`, `payload`, `ledger_entry_id`, `bank_transaction_id`, `document_id`, `risk_level`, `blocker_code`, `created_by`, `created_at`. Its catalog kind is `legacy-business`; do not assign semantic ownership from the table name or an issue label.

The Investment stage exit removes its three row families and restricts allowed types to `dividend_to_owner`, `shareholder_loan`, `tax_settlement`. Governance contract removes its two row families and old writers. Tax is the remaining active writer, but the old table constraint still admits governance labels. A retirement must reject unexpected non-Tax survivors and malformed/conflicting data atomically; no hosted row prevalence is inferred. Count/hash and original JSON/identifier/time reconciliation are required before retirement. Any claimed compatibility-resource ownership must be justified by that complete retirement condition, not an invented general split-resource exception.

The current Tax routines are in `supabase/migrations/20260827100500_ledger_writer_coordinators.sql`. They claim immutable workflow identity, lock the company/year, enforce date/year and amount/kind/document rules, reject a payable bank link, check same-company/year bank/document bindings and exact unmatched/no-warning signed bank amount, append the holding action, claim its bank match, and complete the technical workflow receipt. Ordinary callers use the restricted backend session with independently verified actor context; migration/grant/definer details must be rehearsed as shipped, not inferred from a role name.

The Ledger contract intentionally removed the old holding-action Ledger FK. Banking retargeted its FK to `banking.transactions(id) ON DELETE RESTRICT`. Preserve these reference semantics and opaque identity. Technical `backend_system.ledger_workflow_receipts` remain backend-system state; their name alone is not grounds to move or duplicate receipt ownership.

Current `claim_ledger_writer_v1` fingerprints complete JSONB request text, including correlation ID. Web supplies the same operation UUID for both headers. Accepted membership/owner checks precede replay; company-year admission and period locks follow only when a receipt is absent. The distinct existing-action fallback checks company/type but does not compare every field when the supplied receipt key is absent. Characterize this branch explicitly before deciding canonical conflict/replay handling.

## Frozen scope and later work

The Company Tax facade contains one `import_company_tax_tt02_evidence` / `recordCompanyTaxReturnTt02Evidence` tuple, removed in #152. The former settlement web persistence scopes were already retired atomically by the approved #139 relocation. The #151 sixteen-entry amendment is not permission to alter unrelated tuples. Keep `compatibility-baseline.json` byte-identical and preserve all future scopes and occurrence counts except an independently proven current-resource retirement under existing ADR authority.

`estimateAnnualTax` shares the settlement TypeScript file and tests but belongs to #152. Preserve it and its callers while deleting only settlement policy. Generic tax filing rows, current Annual Compliance readiness, Audit/Notifications implementation and company-tax provider behavior remain their existing owners.

## Characterization and rollback assets

Existing sources include `tests/tax_settlement.test.mjs`, `tests/test_ledger_and_actions.py`, `apps/backend/tests/test_ledger.py`, `test_ledger_api.py`, `test_supabase_ledger.py`, Ledger database/schema/boundary tests, web Ledger presentation/audit tests, the workspace SQL test, original generated client/OpenAPI and the complete predecessor SQL chain. The supplemental 19-case capture in `legacy-preview-cases.json` binds exact old source bytes and Node 24.20.0; it is preview characterization only and does not certify backend/calendar/year/authorization/database behavior.

The pinned source inventory includes applicable expand, contract and reverse assets for Ledger, Banking, Investments, Documents, Governance and RF. New Tax rollback must preserve prior immutable Ledger entries, bank matches, Audit identity, opaque document references and archive generations; quarantine new Tax state, reject conflicts, restore one writer in the matching application/schema phase and support recutover. Do not restore unrelated retired foreign keys, privileges, or prior owners.

The detailed characterization/cutover plan enumerates the required negative, database, generated-client, browser, deployment-order, rollback and independent-review proof. Entry evidence does not count toward either final immutable gate. No live provider, hosted migration, real filing, paid service or production promotion is included. Production remains frozen at `d331ee2717d1eeacef0d81db42b9d4fb5848b408` on `release/production`.
