# Corporate Document Backup and Restore Runbook

Status: required before corporate-document production enablement  
Last updated: 2026-07-14

This runbook covers immutable corporate decisions, document sets, unsigned and owner-attested signed PDF variants, lifecycle events, finalizations, and accounting-policy version references. JSON archives contain metadata and authenticated private-storage references only; they must never embed raw signed PDF bytes.

## Required evidence set

- company/year archive JSON from `/archive/{companyId}/{incomeYear}/download`;
- backup manifest containing counts for every corporate lifecycle table;
- privileged database backup of referenced immutable accounting-policy rows (company archives expose version references, not policy contents);
- one object reference per unsigned and signed artifact with storage key, SHA-256, byte length, kind, and variant;
- encrypted object backup containing the referenced private PDFs;
- isolated database restore target and isolated private storage target;
- command output, operator, UTC timestamps, source commit, target identifiers, and final pass/fail decision.

## Backup rehearsal

1. Use a synthetic company with both annual-close artifacts and a finalized owner-dividend declaration/payment. Authenticate as an accepted owner with fresh MFA.
2. Export each affected company/year. Confirm the archive records `corporateDecisions`, `corporateDocumentSets`, `corporateDocumentArtifacts`, `corporateDocumentEvents`, and `corporateDecisionFinalizations`.
3. Build the manifest with `buildBackupManifest`. Confirm both `unsigned` and `signed_owner_attested` variants are present and that no `pdfBytes`, base64 body, token, or signed URL appears in the JSON.
4. Download every referenced object through an authenticated private-storage client. For each object, independently verify `%PDF-`, byte length, and SHA-256 against the manifest. A missing or mismatched object fails the rehearsal.
5. Store the archive, manifest, verified PDFs, and command output in the approved encrypted backup location. Do not place signed PDFs in Git, tickets, chat, or unencrypted local folders.

## Isolated restore rehearsal

1. Create isolated database and private-storage targets. Never rehearse destructive restore operations against production.
2. Apply migrations in lexical order, including `0004_corporate_document_artifacts.sql`.
3. Restore company/accounting rows first, then corporate decisions, sets, artifacts, events, and finalizations while preserving their immutable IDs and hashes. Restore referenced PDF objects to the isolated private bucket.
4. Run `restoreCompanyYearArchive` and `assertRestoreIntegrity`. Any missing set, artifact, event, finalization, relationship, document row, storage key, content hash, or byte length fails the restore.
5. Re-download every restored corporate object and independently compare SHA-256 and byte length with the manifest.
6. Verify an accepted owner can read the restored lifecycle and preview the PDFs. Verify a reviewer/read-only member has only the intended read access. Verify an unrelated authenticated user and anonymous user cannot read rows or objects.
7. Verify direct authenticated insert, update, and delete remain denied on all corporate lifecycle tables, and that private object overwrite is denied.
8. Record a `security_restore` signoff only after all checks pass. Evidence expires after 30 days.

## Cancellation and deletion

Cancellation remains `export_required` until the application has recorded a real company/year archive export. If a corporate artifact was created after that export, a new export is required. Final deletion remains blocked by retention/legal review even after export evidence is complete.

## Failure handling

- Stop immediately on a missing object, hash/length mismatch, cross-tenant access, mutable lifecycle row, or relationship mismatch.
- Preserve logs and identifiers without copying document contents or personal identifiers into incident channels.
- Keep `TALLI_CORPORATE_DOCUMENTS_ENABLED=false` and invalidate any release approval tied to the failed evidence.
- Repair through a new immutable artifact/decision or a new backup; never overwrite an approved object or mutate historical lifecycle evidence.
