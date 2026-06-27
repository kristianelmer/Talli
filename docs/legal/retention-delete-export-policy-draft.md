# Retention, Deletion, and Export Policy Draft

Status: draft for founder/legal review  
Last updated: 2026-06-27  
Blocks: #72 remains open until human/legal signoff

## Policy Goal

Users must be able to leave Talli without lock-in, while Talli avoids deleting
records that may need to be retained as accounting documentation, filing evidence,
or audit/security logs.

## Export Before Cancellation

Before cancellation/deletion, Talli should generate a company archive containing:

- company identity;
- memberships and reviewer comments;
- opening balances and shareholders;
- ledger entries;
- holding actions and investment positions;
- documents metadata and object references;
- filing previews, submissions, feedback, receipts, and overrides;
- billing/refund state;
- audit events relevant to the selected company/year.

If document bytes are missing from object storage, export must include explicit
missing-object warnings.

## Archive Responsibility After Export

Once a company archive has been exported to the customer, the customer/user is
responsible for safekeeping that exported copy. Talli's own copy is kept only for as
long as the retention classes below require, and Talli's copy may be deleted once the
applicable retention hold expires. Talli does not warrant indefinite availability of a
company's data after cancellation; the export is the customer's durable record.

## Retention Classes

| Data class | Default handling |
| --- | --- |
| Source documents and balance documentation | Retain minimum 5 years after end of accounting year (bokføringsloven § 13) before deletion. |
| Filing payloads, feedback, receipts | Retain as filing evidence for minimum 5 years while statutory/accounting retention applies. |
| Ledger, holding actions, opening balances | Retain with accounting records, minimum 5 years. |
| Audit/security logs | Retain long enough for security, dispute, and compliance evidence. |
| Billing records | Retain as needed for accounting, tax, refund, and dispute handling (minimum 5 years). |
| Invitations and notification outbox | Retain short operational history; redact/expire tokens where possible. |
| Auth/account profile | Delete/anonymize when no longer needed, subject to retained company/audit references. |

The 5-year floor reflects the Norwegian Bookkeeping Act (bokføringsloven § 13)
minimum for primary accounting material. Longer periods or shorter periods for
specific secondary documentation should be confirmed with the company accountant.

## Deletion Rules

- User-requested deletion must not silently remove statutory accounting records.
- Company deletion requires fresh MFA/step-up and human security review.
- Destructive deletion must be audited.
- Cancelled companies should enter retention hold where legal retention applies.
- Final deletion should happen only after retention hold expires or legal review approves.

## User Identifiers in Retained Audit Records

When a user account is deleted but audit/security logs must be kept (for security,
dispute, and compliance evidence), user identifiers in those retained records are
pseudonymized: the user's account id is replaced with a stable opaque token. This keeps
the audit trail internally consistent and linkable for investigation while no longer
directly identifying the person. The mapping needed to re-identify, if any is kept, is
held under restricted access and deleted when no longer legally necessary.

## Required Human Review Before Publication

- [x] Confirm exact retention periods — minimum 5 years per bokføringsloven § 13.
- [x] Confirm whether Talli or customer is responsible for retained archive after export —
  customer is responsible for the exported copy; Talli's copy is deleted after the
  retention hold expires.
- [x] Confirm deletion/anonymization approach for user ids in retained audit records —
  pseudonymize with a stable opaque token.
- [ ] Confirm cancellation copy and support runbook.
