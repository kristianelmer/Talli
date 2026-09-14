# Accounts inactive database expansion

The CLI-created artifact expands only after contracted Company Tax. Six private
Accounts tables copy the remaining generic rows with original columns, IDs,
constraints, indexes and rebound intra-Accounts foreign keys. Seven synthetic
rows cover all six families and both simulation and test-authority submissions.
Every family reconciles source/target count and PostgreSQL JSON row hashes.
Original source rows and existing role memberships stay unchanged.

Every remaining row must positively match Accounts and matching referenced
company/year/obligation. Unknown or conflicting records are copied unchanged to
private quarantine with their hashes; they are not assigned an owner or deleted.
A populated unknown preview and its comment were retained in source and quarantine.
The migration records all six table definitions and 37 dependent routine bodies,
owners and grants. The legacy comment target rf1086_preview stays unchanged.

Accounts owns the six inactive business tables. Backend System owns phase,
inventory, source rows, quarantine and reconciliations. FORCE RLS, no business
policies and revoked runtime grants make targets unavailable. Sixty populated
read/insert probes cover anon, authenticated, service_role, workflow executor and
store owner; runtime access is denied and the owner cannot read/write business
rows without policies. The original accepted owner can still write legacy data.
Seven additional classifier probes reject unknown or inconsistent provenance.
These SQL role claims are synthetic and are not HTTP JWT/MFA evidence.

All expanded-probe transactions rolled back. An initial synthetic submission
incorrectly combined simulation and authority-reference modes; fixtures now
exercise the two valid modes separately. A later harness could not SET the
properly restored store role; explicit test-only SET grants were added after
verifying migration membership restoration. A current_user shorthand GRANT
crashed the local Postgres process. It recovered and rolled back; the explicit
runner/grantor form passes. The diagnostic artifact preserves this limitation.

After rollback probes, expansion alone was committed on the disposable
accounts153_lifecycle_d060 clone. No source, hosted or production database was
changed. Supabase CLI 2.109.1 advisors required sslmode=disable for this local
socket endpoint: 46 findings, zero blocking, zero Accounts-specific findings.
Architecture enforcement passes. The artifact filename was created by installed
Supabase CLI 2.62.5 migration new, then placed in the explicitly ordered contract
artifact directory. It does not auto-activate a writer.

The previous authority fix reviews both pass and are adopted byte-exact.
This is not a full stage exit. Authenticated read/write contracts, generated web
workflow, source handoff, cutover/contract/rollback, Archive integration and all
six original #153 acceptance criteria remain pending.
