# Accounts physical retirement and final shared reads

This bounded checkpoint adds explicit dependency, cutover, contract and paired
rollback artifacts for the six remaining generic filing families. It moves the
Archive reads to the Accounts generated client while retaining company-wide
comments and permissions, requested-year filings and linked evidence. The
catalog proves deletion of all six public tables before their compatibility
aliases identify the Accounts owner. Exactly 24 active scopes are removed from
the prior 60; the immutable 237-scope baseline is unchanged. Eight Audit and two
Notification continuations retain their original persistence chains. Eight
bounded action/Archive AST pins and retained-sibling checks remain enforced even
after the last reattributed RF scope is removed.

## Database proof and corrections

All database checks used the owned loopback disposable clone and rolled back
fixtures, schema changes and global memberships. No hosted migration, provider
operation or production change occurred. The local gate now declares the
Accounts lifecycle lane and explicit activation after the final Tax topology;
that entire integrated gate has not yet run for this checkpoint.

The final SQL passes 17 permanent lifecycle cases, 47 real authorization/control
cases and 48 direct API role/function privilege denials. The final eleven-phase
rehearsal preserves a new evidence row and an acknowledgement on an existing
comment through contract rollback, full rollback, re-cutover and contraction.
The permanent lane additionally verifies Documents receipt/feedback retention
without caller membership, Tax coverage after public tables disappear, source
and target drift, old-writer fences and first-index-inventory preservation.

The original Spec review reproduced two P2s: missing FORCE RLS on an inactive
owned table could expose a foreign preview after cutover, and disabled public
RLS could expose restored rows after full rollback. Standards found the related
public trigger-drift branch. The original SQL, reports and reproductions are
retained. The corrected cutover attests exact reviewed target structures before
its temporary migration policy. Full rollback compares original public owner,
ACL, RLS, columns, constraints, policies and triggers before copying or restoring
writes. Only separately verified rollback fences are normalized. Independent
follow-up reviews bind the corrected bytes; original failures are not replaced.

The target fingerprint JSON is a complete reviewable clean-schema capture from
the five named pre-cutover artifacts. Its query normalizes role names and covers
effective ACLs, owner privileges, relation kind, columns/defaults, constraints,
indexes, RLS/FORCE RLS, policies and triggers. The capture's producer/query/input
hashes are retained. Historical private reproducers retain their original path
references; the permanent repository lifecycle test is the portable gate entry.

Initial permanent-harness failures retain the SQL CASE syntax error and its fix,
then corrected harness expectations for membership-before-phase errors, the RF
legacy trigger rejecting before CHECK(false), Tax's repeatable-read requirement,
and receipt fixture placement before cutover. The final pass does not relax
those runtime guards. Earlier standalone probe hashes remain historical; final
current-byte authorization and eleven-phase receipts are separately bound.

## Web and architecture verification

35 focused workspace, Archive and generated-client tests pass. The exact action
mutation test, immutable-inventory and completed-RF retirement tests pass, and
the manifest/dependency test and architecture checker pass. The first complete
architecture test run exposed stale expected inventories and a real gap where
mixed-action enforcement ended when the last handoff disappeared. The corrected
checker keeps that enforcement while sibling calls remain. The original failed
run and targeted passing follow-ups are retained. This is not a claim that the
complete architecture suite or complete customer-ready gate has passed at this
checkpoint.

The previous bounded web Spec and Standards PASS reviews at 5279d43e are adopted
byte-for-byte. No original acceptance criterion or stage-exit status is marked
complete here. Durable source handoff, duplicate TypeScript retirement, complete
hydrated workflow verification, final advisors, protected integration and the
full two-revision stage-exit envelope remain required before #193 and #149.
