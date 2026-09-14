# Accounts legacy characterization

Both independent inventory axes passed revision `20747014`. The entry inventory
and requirements are historical evidence at that revision; this directory records
the subsequent characterization phase. All six original issue criteria remain
pending. No application or SQL implementation has changed.

The live profile has 67 payload, 175 XML, 43 evidence-import and 11 Accounts-only
readiness cases. The capture imports the unchanged baseline implementation on
Node 24.20.0. The private readiness function is exposed by adding an export and
making imports absolute; its body is unchanged. Inputs, full outputs, ordered
errors, XML bytes and non-finite/negative-zero diagnostics are retained. XML
captures include every required field's absence, duplicate and ORID mismatch,
whole-integer/negative/consistency failures, UTF-16 lengths, escaping and dates.

The distinct offline profile has 46 Python 3.12.12 cases plus the existing public
validation fixture report. Its 22-field projection, Python rounding, account
coverage, attachment decisions, readiness and simulation receipts stay separate
from the live 21-field projection. Before replacing policy, Accounts-specific
offline behavior must receive a canonical owner and explicit public contract
profile. Common AnnualData, Tax and Archive behavior remains outside this stage.

The 61 exact-body Server Action executions use deterministic time and synthetic
dependencies. They establish call order and payloads, not real authentication,
SQL or transport. The original import always records signed-and-archived TT02
evidence as pending. Its Audit continuation occurs after the evidence insert;
a returned Audit error is currently ignored while a thrown exception escapes.
That distinction is captured, not reclassified as transactional atomicity.

The disposable local database clone supplies 87 populated RLS probes. All data
and updates are rolled back, including synthetic users and company. A preliminary
86-case capture encountered the existing unique submission-per-preview constraint
before isolating insert access. The final capture uses fresh synthetic previews
for insert probes and separately records that duplicate rejection. There is no
retained business fixture, hosted mutation or populated migration/rollback claim.

The legacy direct RLS admits an unaccepted owner and AAL1 writes; the server
actions separately enforce fresh MFA for permission/evidence operations. These
are observed baseline limitations, not permission to reproduce an authorization
bypass in the canonical backend. The new request boundary must enforce current
accepted membership and applicable action-time MFA before the owned writer.
Negative authorization cases remain mandatory before stage exit.

Existing checks passed: 138 no-provider authority workflow/transport tests and 46
web Accounts/evidence/mixed-action tests, with no failures or skips. Neither these
checks nor the captures count as an immutable complete exit gate.

Remaining before exit: canonical implementation, authenticated generated-client
workflow, populated migration reconciliation, single-writer deployment protocol,
rollback/recutover and RLS, legacy retirement, source handoff, independent reviews,
and two consecutive complete immutable gates. No provider interaction, genuine
filing, production activation or promotion is included.
