One P2 finding — STD-193-RF-DIALOG-1: preserve complete attachment attribution before final acceptance.

In dialog_feedback.py:54–67, each document receives an exact transmission/attachment reference, but _FeedbackJournal.record_artifact (postgres_shareholder_register_filing.py:817–825) deduplicates solely by content SHA and returns without recording a different reference. The inherited SQL unique(submission_id, sha256) has the same shape. A related PDF plus two distinct XML attachment IDs containing identical bytes therefore requests three attachments, persists only two references, then records accepted. Complete source identity cannot subsequently be reconstructed.

This breaches the new MODULE.md “Related authority feedback” contract that retains exact Dialogporten IDs and provider creation time before the final decision, alongside ADR0011’s capability-owned immutable fact boundary. Retain a complete, durable attribution manifest separately from deduplicated receipt bytes, or fail closed on attribution mismatch. This is a concrete persistence-contract defect, not a Fowler heuristic.

The independent reproduction uses actual public reconciliation and actual _FeedbackJournal.record_artifact with local SQL/Document fakes. It observes three requested attachments, two retained attributions and one accepted event; it does not claim persisted runtime proof. Original producer, output and frozen source are retained. The parent acknowledged the defect and is developing a separate fix; no fix bytes are included here.

Other checks: 483 focused tests and four independent token cancellation/construction-failure checks passed. Tokens share exact delegation, both are discarded on those failures, provider requests remain fixed-host GETs, diagnostics omit raw bodies, and the new parameterized confirmation read stays under the existing RF role/lease boundary. No additional material heuristic finding.

Scope: fifteen frozen WIP files against c4d9fb2fe27b2d2c3e9be077f03146c0b391bfe2, including untracked integration files. No source edits, provider/browser/key access or database operations; no full RF gate or #193 acceptance credit. Later runtime tests and fixes are excluded.
