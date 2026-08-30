# Retention, Deletion, and Export Policy Draft

Status: founder/accountable-owner retention direction approved; hosted deletion evidence pending
Last updated: 2026-08-30
Blocks: #72 remains open until hosted retention, backup, purge, and deletion evidence is recorded

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

Once a company archive has been exported, the customer is responsible for
safekeeping that copy. Talli provides the approved paid-access period followed by
at least 90 days of read-only access and export. Talli then returns or deletes
customer-controlled data according to the customer's documented choice, unless a
legal duty applies directly to Talli or the customer gives a lawful documented
retention instruction. The customer's bookkeeping duty is not a general reason
for Talli to retain all customer data.

## Retention Classes

| Data class | Default handling |
| --- | --- |
| Customer-controlled source documents and balance documentation | Return or delete after the agreed access/export period at the customer's documented choice. Retain only on a lawful customer instruction or a legal duty that applies directly to Talli. |
| Customer-controlled filing payloads, feedback, receipts | Return or delete under the same rule; do not assume Talli has an independent five-year right. |
| Customer-controlled narrow ledger, holding actions, opening balances | Return or delete under the same rule; the customer's exported company archive is its durable record. |
| Audit/security logs | Retain long enough for security, dispute, and compliance evidence. |
| Billing records | Retain as needed for accounting, tax, refund, and dispute handling (minimum 5 years). |
| Invitations and notification outbox | Retain short operational history; redact/expire tokens where possible. |
| Auth/account profile | Delete/anonymize when no longer needed, subject to retained company/audit references. |
| Optional public-measurement browser session | No more than 30 minutes in one browser tab. |
| Optional public-measurement raw events and minimized consent proof | No more than 90 days. |
| Optional public-measurement withdrawal tombstone | No more than 30 minutes. |
| Invited-pilot raw observations | No more than 90 days. |
| Protected invited-pilot participant register | Delete 12 months after validation ends, unless an incident or legal requirement needs longer storage. |

The Norwegian Bookkeeping Act generally requires the bookkeeping entity to keep
primary accounting material for five years after the end of the accounting year.
From 1 January 2027, amended section 13 also requires specific review where
bookkeeping and storage are entrusted to another provider. Talli must record the
exact duty that applies to it before relying on that law for retention. It must
not convert the customer's duty into an unrelated blanket hold.

## Deletion Rules

- User-requested deletion must not silently remove statutory accounting records.
- Company deletion requires fresh MFA/step-up and human security review.
- Destructive deletion must be audited.
- A cancelled company enters retention hold only when a documented customer
  instruction, direct legal duty, incident, or other recorded legal hold applies.
- Final deletion happens after the approved export period, backup rotation, and
  any documented hold expire.

## User Identifiers in Retained Audit Records

When a user account is deleted but audit/security logs must be kept (for security,
dispute, and compliance evidence), user identifiers in those retained records are
pseudonymized: the user's account id is replaced with a stable opaque token. This keeps
the audit trail internally consistent and linkable for investigation while no longer
directly identifying the person. The mapping needed to re-identify, if any is kept, is
held under restricted access and deleted when no longer legally necessary.

## Approval and Remaining Evidence

- [x] Confirm customer-content rule — return or delete after approved export at
  the customer's choice; retain only on direct law or lawful instruction.
- [x] Confirm measurement periods — 30-minute session, 90-day raw events and
  consent proof, 30-minute withdrawal tombstone.
- [x] Confirm pilot periods — 90-day raw observations and 12-month protected
  participant register after validation ends, subject to incident/legal hold.
- [x] Confirm deletion/anonymization approach for user ids in retained audit records —
  pseudonymize with a stable opaque token.
- [ ] Verify hosted backup rotation, automatic purge, deletion, and cancellation
  runbook against the exact production systems.
