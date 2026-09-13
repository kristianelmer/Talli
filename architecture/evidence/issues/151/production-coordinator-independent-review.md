# Independent review: canonical RF production coordinators

Observed 2026-09-09T21:27:54.513779+00:00. Baseline `91b178c281bcc5fb887a6257d2f72e380199f3e6`; current working tree HEAD `7730bd3473943f5308136207b2acce4f720c851c`. Source hashes below identify the reviewed uncommitted snapshot.

**No materially actionable regression found in the assigned slice.** This is a bounded source/spec comparison of production.py, feedback.py and the two send/reconcile functions in the application workflow. It excludes my PostgreSQL adapter, SQL, migrations and persistence tests from independent certification. No tests, database or provider operations were run.

## Comparison and preserved invariants

A read-only Python AST comparison covered 27 corresponding functions against the #150 compatibility module. Twenty-two are AST-identical. Four differ only in the canonical session/error type names. The remaining function, `rf1086_current_manifest`, accepts list or tuple documentHashes and recursively normalizes immutable mappings/tuples for its final equality check. Public DTOs now freeze lists into tuples and mappings into MappingProxyType; this adaptation preserves the same document name/digest multiset, original approved order, exact required fields, complete manifest equality and final hash. The safe error allowlist remains identical. Public lazy exports target the reviewed owner implementations.

- **Send order:** UUID validation and configuration precede approval read; invalidation, fresh owner/MFA, preview, Billing snapshot and entitlement, company identity, accepted bound System User, canonical document order and full approved-manifest hash checks precede the provider binding. `bind_mutation_authority` is awaited before `begin_production_filing`, exactly as before. The provider binding is discarded in finally. This certifies coordinator invocation order, not the excluded adapter’s implementation of token acquisition or locked SQL gate checks.
- **One journal and retries:** prepare persists each operation before its provider call; stored name/body hash/key are required; success reuses its reference; unknown stops without a send; retryable failures preserve the key and normalize the next attempt; the twentieth-attempt cap remains unchanged. Main/subdocument/confirm/read ordering and per-operation body hashes are AST-identical.
- **Recovery:** caller and retained submission ownership/bindings are checked; terminal retained states return without provider work. The historical path reads the retained Billing snapshot and matching approval/connection/preview, but adds no current entitlement decision, approval invalidation rejection or fresh-MFA gate. It claims a lease before resolving the persisted reference and binding only the read-only authority. The recovery code never receives or invokes a mutation authority, begin, or operation-journal writer. Binding discard and claimed-lease release remain in finally.
- **Feedback and receipts:** both original namespaces, XML safeguards and submission/year classification are unchanged. Initial send uses five bounded archive polls, recovery one; each non-inline document is fetched by GET. Raw bytes, TextEncoder-compatible inline conversion, SHA256, content type, submitted-document exclusion, durable artifact result handling, conflict classification and safe errors are unchanged. Feedback append occurs after artifact processing with accumulated hashes. Unknown mutation outcomes cannot silently restart this workflow.

The newly added command wrapper checks command.actor_id against the authenticated session before delegating send/reconcile, and exposes no browser-supplied provider token or release facts. The protocol retains distinct mutation and read-only bindings. No additional business writer, changed obligation/year policy or source ownership was observed in this slice.

## Bound source artifacts

| Artifact | SHA256 |
| --- | --- |
| Baseline `apps/backend/src/talli_backend/compatibility/rf1086_authority_workflow.py` at `91b178c281bcc5fb887a6257d2f72e380199f3e6` | `70fc1020b266e85ebaaa39252c826ffe3c447ad264266a9f46f7ebce7b96bd23` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/production.py` | `ce338e62aca5e286117f86e5602227d87f93c8f42808b1de36acb0488624c7a7` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/feedback.py` | `f899542eccf62d22fbed127edde9ee30b35f2f0e6563357c0e84d86d09b0f4d9` |
| `apps/backend/src/talli_backend/application/shareholder_register_filing_workflow.py` | `9319817c3408089e5e01badfbb6d98f9a325b0b3c128a6bf06628c45f9516077` |
| `apps/backend/src/talli_backend/application/shareholder_register_filing_session.py` | `9cf23d8c6c197c6c0745f59d36a17f16acac08ee239409239b2370435936e7c6` |
| `apps/backend/src/talli_backend/modules/shareholder_register_filing/public.py` | `a9c0c54763ec7311d03b2370b961a6509ed6927ff157a28a252cbf0daee6a674` |

Read-only function-level comparison: `/tmp/talli-151-production-ast-comparison.json`. Import and DTO inspection was limited to proving the moved coordinator bindings and immutable-container adaptation. Full migration, adapter, database, API, browser and gate evidence must be assessed separately.
