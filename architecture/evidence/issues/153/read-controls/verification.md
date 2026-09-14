# Accounts authenticated read and preparation contracts

Eight additive HTTP endpoints now bind the verified actor to Accounts-owned
workspace, preview, override, review, acknowledgement, permission, manual test
evidence and TT02 import operations. Fourteen wire schemas and the generated
client preserve every pre-existing OpenAPI schema and path unchanged. The
workspace returns complete immutable company/year rows, rejecting wrong
obligations, duplicate IDs, missing links and scope conflicts. Sensitive routes
send no-store responses; generated reads also reject foreign result scope.

Three CLI-created SQL artifacts add read, preparation and import contracts after
expansion. Every business entry point requires cutover/contracted phase. Company
Access retains accepted membership, owner/reviewer and fresh MFA decisions.
The TT02 importer retains the original single authority_test_runs INSERT with
pending status; it adds neither Tax submission persistence nor replay deduplication
nor atomic Audit. The web action's existing subsequent Audit insert is still
unchanged, and its cutover to the new client remains pending. Projection time is
supplied by the application clock and actor/organization come from verified
session and Company Access identity. No provider operation is introduced.

Forty-seven synthetic SQL cases pass on accounts153_setup_fix_d060, plus 36
negative execute-privilege checks across anon/authenticated/service_role. The
probe changes phase only inside its rolled-back transaction, not through a real
cutover. It covers accepted owners/reviewers, unaccepted membership, outsiders,
stale MFA/AAL1, inactive reads/writes and malformed TT02 projections. Global
memberships, schema and fixtures restore after rollback. The first expectation
assumed reviewer-forbidden for locked owner-only records; FORCE RLS correctly
conceals those records as not-found, and that failed expectation is retained.

Sixty-two focused Python tests pass, including 41 frozen TT02 HTTP cases, actor
binding, immutable workspace scope/link checks and persistence rollback. The
broader Accounts suite passes 2,272 tests. Initial HTTP checks identified the
missing no-store header, which is fixed. Two generated-client tests pass; TypeScript
checking and both generation drift checks pass. Architecture checks pass after
completing the declared interface and composition inventories; failed intermediate
inventory checks are preserved. No full-stage or actual JWT ceremony credit is
claimed. Web cutover, canonical source handoff, contract/rollback, Archive integration
and the complete #153 stage exit remain pending.

The original 04e682b6 Standards PASS and both e6f8e889 setup-provenance fix PASS
reports are adopted byte-exact. Their earlier evidence remains unchanged.
