# Workspace RF assertion relocation

Scope: RF-only sections of tests/supabase_workspace.test.mjs. The existing company invitations, tax evidence import, annual-data/readiness, billing predecessor history, banking, ledger, document security, archive and audit/notification assertions remain.

| Predecessor assertion | Canonical successor |
| --- | --- |
| Insert 2025 opening snapshot/shareholder through public tables | Explicit historical source-only RF and Ledger bank-input seed; no fabricated live company-year admission; actual Ledger opening-snapshot API readback |
| Reload opening / outsider sees no source | Actual generated Ledger opening-snapshot query; outsider denied by authenticated API |
| TypeScript → Python render then client insert of generated XML | Actual generated RF preview command, actual preview query; ready status, Norwegian filing label, company text and stored XML checked |
| Client inserts RF permission | Actual RF permission command from separate real MFA session and owned workspace projection; reviewer/outsider denied; sibling tax/accounts permission writes unchanged |
| Tax evidence import has no authority/launch side effect | Original public sibling permission/launch/audit comparisons plus independent canonical RF permission before/after equality |
| Client validates/inserts advisory override | Actual owner command + stored scope/risk/actor projection; original web audit insertion unchanged; read-only command denied |
| Production TypeScript adapter disabled | Actual shipped production HTTP route returns configuration_unavailable while all production flags/credentials are absent; no provider I/O |
| Client simulates, hashes, upserts receipt | Actual canonical simulation command; independent original JS hash calculation; stored call count, actor, metadata, exact XML and receipt relation checks |
| Repeated upsert preserves one receipt and keys | Repeated actual simulation command; same record UUID, one submission, unchanged receipt/hash/operation keys |
| Local blocking-override function throws | Actual blocking override persists and actual simulation command returns409 without adding another submission |
| Outsider public RF reads empty; reviewer visible | Actual workspace/preview authenticated denial; reviewer actual preview visible |
| Reviewer inserts advisory comment; owner acknowledges | Actual commands and owned readback; read-only command denied, owner acknowledgment identity/time checked |
| Hard review block cannot be acknowledged/sent | Actual hard-block comment; acknowledgment fails and remains unacknowledged; simulation fails409 |
| Locked2026 public opening insert fails | Actual full Ledger new-year command fails409, no2026 opening projection appears |
| Mixed archive authority permission input | Frozen sibling public rows plus canonical RF owned permission projection; original archive receipt/hash/XML checks retained |
| Public RF fixture deletes | Exact scoped RF graph + Ledger bank-input cleanup, original FORCE RLS/membership restoration, zero RF residue; sibling public cleanup retained |

Test-only utilities: tests/support/rf1086-workspace-api.mjs starts a real loopback FastAPI process and temporarily activates only the two existing restricted backend logins, restoring NOLOGIN/password-null after stopping it. tests/fixtures/start_rf1086_workspace_backend.py rejects hosted endpoints, all provider activation and ambient provider credentials; process-wide egress guard remains active. Production startup/composition is unchanged. Separate rfOwner MFA session preserves the original owner's aal1 tax-import rejection.

Validation so far: JavaScript syntax checks and7 fixture safety tests pass. Full real workspace/database journey not yet run; architecture agent owns the isolated database. No provider calls or hosted operations performed. This is synthetic local evidence, not historical TT02 authority evidence.
