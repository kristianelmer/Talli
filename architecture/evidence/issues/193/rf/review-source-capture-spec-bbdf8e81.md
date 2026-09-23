# Independent bounded specification review

Reviewed commit: `bbdf8e818842095204f69e103094d0e83d041ef6`.
Base: `8be0d5581ba154ed9939b1b4b2c49e725b433732`.
Diff: `git diff 8be0d558...bbdf8e81`.
Date: 2026-09-23.
Verdict: **two P2 findings; follow-up verification required**. This is the
specification/code axis of the coordinated review, not a release approval.

## Scope and independence

Reviewed other authors' immutable RF year-source and register-observation
persistence, closed codecs, independent register rules, shared chronological
register projection, Documents verification and atomic retention, owned SQL
functions, RLS/grants, rollback and rehearsal guards. The review followed the
accepted requirements in `requirements.json`, issue #193, the year-source and
register-observation design documents, and ADR 0011/0012.

Primary implementation files:

- `apps/backend/src/talli_backend/adapters/postgres_shareholder_register_filing.py`
- `apps/backend/src/talli_backend/adapters/postgres_document_evidence.py`
- `apps/backend/src/talli_backend/adapters/supabase_documents.py`
- `apps/backend/src/talli_backend/modules/shareholder_register_filing/year_source_storage.py`
- `apps/backend/src/talli_backend/modules/shareholder_register_filing/register_observation.py`
- `apps/backend/src/talli_backend/modules/shareholder_register_filing/readiness.py`
- RF and Documents public contracts, module manifests and documentation.
- `apps/backend/src/talli_backend/modules/documents/evidence.py` and `service.py`.
- The migrations and rollbacks dated `20260923091509`, `20260923102314` and
  `20260923102419`, plus the existing Documents reference/removal contract they use.
- `scripts/rehearse-authority-topology.mjs` and associated runtime/unit tests.

**Self-authorship exclusions:** this reviewer authored the new Governance/Ledger
reporting-year evidence slice, source-capture application workflow, authenticated
RF session protocol extension, their tests, and their individual evidence
artifacts. Those files were not independently approved by this review. Their
public interfaces were read only to understand composition. This reviewer made
no implementation changes during review.

## Findings

### P2 — Malformed decimal storage values escape the closed codec error contract

Location: `apps/backend/src/talli_backend/modules/shareholder_register_filing/year_source_storage.py:55`,
with exception boundaries at lines 97 and 118.

`Decimal(value["decimal"])` raises `decimal.InvalidOperation` for a syntactically
invalid decimal string. Neither public parser catches that arithmetic exception.
Consequently a malformed stored source or observation raises an unclassified
runtime exception instead of `rf1086_source_storage_invalid` or
`rf1086_register_storage_invalid`. This violates the codec's stated closed
diagnostics and ADR 0012's stable error boundary. It still rejects the data; the
finding concerns predictable failure handling, not acceptance of altered facts.

Reproduced against an extracted, unchanged copy of this commit by passing each
parser its correct codec envelope with `snapshot: {"decimal":"not-a-number"}`.
Both returned `InvalidOperation`. Existing corruption tests cover `NaN`, which
constructs successfully and follows a different rejection path.

Required correction: normalize malformed decimal arithmetic errors into the
appropriate public storage error for both codecs, and add regression tests using
syntactically invalid decimal strings inside real encoded snapshots.

### P2 — Earlier persistence proof references overwritten private evidence

Location: `architecture/evidence/issues/193/rf/year-source-persistence-20260923.json:37`.

The artifact declares `PASS` and binds three private evidence files by hash, but
all three current files differ from those hashes: `local-runtime.log`,
`local-runtime-result.json`, and `run-local-runtime.py` in the earlier year-source
proof directory. The author confirmed subsequent same-directory reruns overwrote
them and that no original copies are known. The earlier source hashes correctly
describe an earlier implementation; their difference from this checkpoint is
expected. The unavailable test evidence is the finding.

Required correction: preserve the original recorded hashes and explicitly mark
the older private evidence unavailable/not independently verifiable, linking the
newer verified runtime proof as a separate superseding run. Do not replace the
old hashes with hashes of newer material or imply the original run was recovered.

The latest `source-retention-runtime-20260923.json` has nine matching private
evidence hashes; this finding does not invalidate that distinct runtime run.

## Verified behavior and limits

No additional actionable defect was found in the bounded persistence and
retention paths reviewed:

- Source capture and observation corrections take the same company/year advisory
  lock. Identical replay returns the original; corrections preserve originals and
  reject stale predecessors/forks. Source append rechecks observation currentness
  under that lock.
- Current owner, company/year admission and step-up checks precede replay. Reads
  require company membership; owned RLS and grants deny browser/direct mutation.
- Document retention locks exact originals, compares the complete Documents-owned
  metadata digest, and shares the RF append transaction. Metadata mismatch poisons
  the SQL transaction. Late failure rolls back retention and RF records together.
- The existing removal function takes the same document row lock and rejects any
  retained reference. Narrow API rollback preserves originals, references and
  deletion protection; full RF schema rehearsal refuses retained source records.
- The register projection uses the same full chronological replay as readiness,
  including preceding formation/transfer and subsequent closing reconciliation.
  It retains exact decimal economics and validates holder identities.

These are point-in-time capture guarantees. Cross-owner action-time freshness,
source-backed preview/approval/send, nominal-increase Governance support,
historical fund-issued capital and distribution clearance remain documented
unfinished work, not silently reduced product scope. No new customer route or
provider activation is approved by this review.

## Test and evidence verification

- Independently extracted this exact commit into a private review directory and
  ran seven relevant other-author test modules: **154 passed in 0.87s**. This
  avoids relying on working-tree fixes made after the checkpoint.
- Independent unit-log SHA-256:
  `527fddd9f5021fa7d2796a0edbc1f0b997a44d6b5a7904eea3d749646aa16059`.
- Frozen codec reproduction-log SHA-256:
  `aed2c1e3124319cdf681fffb5f39c905ac9d318d39258e0deb3552dd44a3dc6d`.
- `source-capture-integration-20260923.json`: **56/56** source hashes match this
  commit. All four private integration log hashes match; logs report **1,213
  backend tests**, **55 CI/partition tests**, and the architecture run recorded by
  the proof. The exact test-selection manifest also matches.
- `documents-retention-runtime-20260923.json`: **10/10** source hashes match.
- Latest source-retention runtime proof: all **9/9** private evidence hashes
  match. **25/26** source hashes match this commit; its `readiness.py` predates the
  final shared replay update. Therefore the retained **39 restricted-role DB
  tests** are evidence for their bound source version, not an exact-current-tree
  database run. Current replay is covered by the independent frozen unit run and
  current integration offline proof. A fresh exact-checkpoint runtime proof is
  still appropriate before claiming complete integration validation.
- No database mutation, hosted operation, provider call, or production data read
  was performed by this review. Runtime behavior above was checked through source,
  tests and retained hash-bound logs; the reviewer did not rerun the database suite.

All seven full RF acceptance criteria remain **PENDING**. The owner has explicitly
confirmed that no production AS has been recruited; genuine-company acceptance is
not available. Tax and Accounts remain outside this checkpoint.
