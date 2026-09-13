# Independent root integration review — #151

Verdict: **scoped pass after one confirmed response regression was corrected**. This is a working-tree source review, not an immutable stage-exit or complete integration attestation.

Comparison: `git diff 91b178c281bcc5fb887a6257d2f72e380199f3e6 -- <listed paths>`; HEAD is entry-evidence commit `7a49f010`, implementation is uncommitted. The fixed point resolves; the only intervening commit records entry evidence.

## Spec finding — closed

**Historical JSON evidence timestamps were rewritten at the HTTP edge.** In `apps/backend/src/talli_backend/main.py`, the original `Rf1086ReceiptMetadataWire.received_at` (line 1020 before correction) and `Rf1086SubmittedPayloadReferenceWire.stored_at` (1030) used `datetime`; `Rf1086SimulationCallWire.created_at` had the same conversion path. A read-only model reproduction showed original `2026-09-09T12:00:00.123Z` becoming `2026-09-09T12:00:00.123000Z`. The original TS receipt/reference builders persisted their exact `Date.toISOString()` strings and previous reads returned those JSON values unchanged. This conflicted with #151 A1/A3/A4 and ADR0010's behavior-preservation rule, particularly the retained archive/payload-reference boundary.

Root changed only these three nested fields to original strings with timestamp validation. C's new actual workspace HTTP regressions cover all four pinned runtime-simulation oracles and zero/three/six fractional-digit variants. Calls, receipt metadata, submitted-payload reference/payload, feedback, XML, hashes and idempotency keys remain exact. **94/94 API tests passed**, 16.75 s, in `/tmp/talli-151-workspace-nested-json-api.log`. Correction source and regression were independently inspected; finding closed. Ordinary top-level database timestamp transport was not changed.

## Remaining reviewed boundaries

- `main.py`: additive RF routes derive actor/correlation from the verified session/request; strict inputs reject caller-manufactured scope, XML, timestamps and manifests. Reads and errors carry `no-store`. Domain/authentication errors remain bounded. Both existing Send/recovery paths, wire names and response shapes remain unchanged.
- Ledger `public.py`/`service.py`, `supabase_ledger.py`, `ledger_workflow.py`, `new_year_opening.py` and session contracts: original bank input stays Decimal-backed and Ledger-owned; RF command contains no bank field. The new-year sequence remains within one verified, restricted-role transaction: claim/replay → RF opening → original bank input → posting → durable workflow receipt. Returned bank provenance is validated before posting; mismatch raises through the transaction for rollback. Transaction methods use the existing connection, not the ordinary independent connection/retry implementation. New-year read validation is the renamed original projection, preserving tenant/holder relationships and bounded pagination. Existing tests cover >2^53 precision, misbinding, replay and rollback.
- Generated client, RF transport/presentation, `actions.ts` and `server.ts`: generated decoding and bearer/no-store transport remain mandatory; all-year history is retained; company/year and duplicate-identity response checks precede presentation. Preview audit continuation uses backend-returned company/year. Approval sends identities and actual confirmation only. Backend unavailability remains an error, not a TS filing fallback. Pending mixed actions and the finite 15-scope amendment were deliberately excluded from a completion claim.

## Standards and independence

No additional documented-standard breach or actionable baseline smell found in this bounded root slice. Applied AGENTS.md, CONTEXT.md, ADR0010–0013 and module/system contracts; older pre-monorepo advice in `.github/copilot-instructions.md` is superseded by those ADRs where inconsistent. Its Norwegian-first, narrow supported scope and deterministic-output rules remain applicable. Thin HTTP/application adapters are intentional documented boundaries, not speculative delegation layers.

I authored the RF pure/public/preparation/source/CLI work and the archive receiver patch, so **those implementations are excluded from my independent verdict**. I inspected how root code consumes their interfaces, without certifying my own implementation. B's evolving RF persistence/SQL and C's production/provider/browser implementation were not independently certified here beyond the required integration signatures and focused regression evidence.

Final database/browser proofs, historical TT02 regeneration, pending amendment, complete immutable gates and protected integration remain separate pending work. No source edits, database/provider calls or hosted mutations were performed for this review.
