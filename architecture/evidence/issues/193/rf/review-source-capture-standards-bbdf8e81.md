# Independent Standards and semantic review: source capture

Commit: `bbdf8e818842095204f69e103094d0e83d041ef6`  
Base: `8be0d5581ba154ed9939b1b4b2c49e725b433732`  
Result: **CHANGES REQUIRED — one P2 semantic finding.**

## Scope and independence

Reviewed other authors' Documents fresh-owner/byte verification, retention adapter and owned SQL; Governance coherent reporting-year enumeration; Ledger public amendment reader; RF source/register application orchestration and capital provenance; shared readiness register projection. Reviewed immutable Git objects and ran tests from an archived copy of this exact commit. Standards: AGENTS.md, CONTEXT.md, ADR-0011 public ownership boundaries, ADR-0012 additive operational boundaries, ADR-0013 serial RF scope, plus the code-review smell baseline.

Excluded from independent credit: my RF persistence adapter additions, storage codec, RF source/observation migrations and rollback, related database/storage tests, topology guard, and their manifests/proofs. Other reviewers cover those. This review does not certify full RF completion or production admission.

## Finding

**[P2] Preserve exact cents before comparing dividend evidence.** `apps/backend/src/talli_backend/application/shareholder_register_source_workflow.py:44` divides Decimal cents under ambient precision; lines 95–101 also sum converted amounts under that context. An immutable-checkpoint reproduction supplies Governance total/allocation `100001` øre against an RF draft of NOK `1000.00`. Precision 28 correctly rejects it; precision 5 accepts and captures it because the authoritative NOK `1000.01` rounds to `1000.0`. This breaks exact economic source binding. Convert integer cents without context-dependent arithmetic and reconcile allocation sums in integer cents; regress the mismatch and varied Decimal contexts. Root received the reproduction before this report. Later fixes are outside this checkpoint.

## Verification and limits

- Independent focused suite: **138 passed**. Private log SHA256: `8e1dd924c8616352796b836d25608cc1cbfd14b0a434a97cbf1b4a8c909fd53e`.
- Reproduction log SHA256: `6998e989b6a2ce04828df0ce0eda73ded0fc139936a5042b72a9315b92997bb2`; retained beside the immutable archive at `/Users/kristianelmer/.codex/issue-192-private/review-source-bbdf8e81`.
- All **56** integration source hashes match this commit. Latest combined **39-test** database proof has **9/9** private evidence hashes matching. No database/provider actions repeated for this review.
- Earlier pre-retention year-source proof has **3/3 unavailable original private artifacts**: subsequent reruns overwrote them. Its original JSON is preserved, but that backing cannot receive independent verification credit. Latest separate proof remains verifiable.
- No additional ownership, enumeration-completeness, lock/rollback, or currentness defect found in the reviewed scope. Documents compares full metadata after byte reads and retains within the RF transaction; Governance/Ledger reads share one serializable snapshot. External projections remain point-in-time observations, not a cross-owner production lease. The isolated timestamp rejection remains explicitly unexplained.
