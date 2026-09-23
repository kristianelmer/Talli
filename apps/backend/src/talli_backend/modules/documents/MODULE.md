# Documents backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["documents.evidence_references","public.documents"],"ports":["DocumentEvidenceRetentionPersistence","DocumentObjectStorage","DocumentsAuthorization","DocumentsPersistence"],"publicEntryPoints":["talli_backend.modules.documents.public"]}
-->

`documents` owns accounting-document validation, the `public.documents` metadata
lifecycle, the private `company-documents` bucket, integrity hashes, retention,
safe removal and restoration, and document-only backup projections. Uploads are
staged before the backend issues one exact signed object transfer. Finalization
downloads and verifies the stored PDF before recording its byte length and
SHA-256 digest. Preview and download transfers recheck those immutable facts;
download additionally requires AAL2.

The private `documents.evidence_references` registry is the removal-safety
boundary for successor capabilities. A narrow database contract locks and
revalidates document metadata before recording an immutable opaque consumer
reference. Removal takes the same document lock before consulting the registry,
so consumers never expose their tables to Documents and cannot race removal.
The versioned `documents.register_evidence_reference_v1` command is callable
only by explicitly declared backend-system coordinators; consumer capability
roles receive no direct privilege.

Consumers retain only `DocumentId` and a semantic relationship. They cannot
write document metadata or object bytes. Company-archive composition remains
outside this module; only `DocumentBackupObject` is published. Supabase and HTTP
details are private adapters behind `DocumentsPersistence` and
`DocumentObjectStorage`; acceptance policy stays in `DocumentsService`.

The stable contract exports `BeginDocumentUploadCommand`, `DocumentBackupObject`,
`DocumentObjectTransfer`, `DocumentRecord`, `DocumentRestoreObject`,
`DocumentRestorePlan`, `DocumentUploadTransfer`,
`StoredDocumentObject`, `DocumentsError`, `DocumentErrorCode`, `DocumentId`,
`DocumentStatus`, `DocumentTransferKind`, `DocumentsSession`,
`DocumentsSessionFactory`, `DocumentsPersistence`, `DocumentsAuthorization`, and
`DocumentObjectStorage`.
Infrastructure declares its bindings with `documents_persistence_adapter` and
`document_object_storage_adapter` and `documents_authorization_adapter`.

The settlement workflow uses `DocumentBindingQuery`, `DocumentBindingPersistence`, `document_binding_persistence_adapter`. The port binds to `talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction`.

<!-- architecture-inventory
{"ports":["DocumentBindingPersistence"]}
-->

`DocumentsSession.verify_document_evidence` publishes `VerifiedDocumentEvidence`
for authenticated backend consumers. It rereads private object bytes, verifies
length and SHA-256 against accepted metadata, and rechecks metadata and current
owner access before and after object I/O using
`DocumentsPersistence.refresh_actor_role`. The adapter re-reads accepted roles
through the existing Documents authorization port, replaces its cached roles,
and fails closed when fresh authorization is unavailable. Other operations
retain their existing session behavior. The result carries metadata and hashes only;
it preserves the existing integrity classification and does not upgrade an
unsigned or restored document to signed evidence. It adds no browser route or
signed download URL. This is a point-in-time observation, not a cross-capability
lease: a consequential consumer still needs to close its freshness race.

### Transactional retention of RF source originals

`DocumentEvidenceRetentionCommand` identifies one RF source/observation and its
verified original document, actual document income year, actual status, content
hash/length and complete metadata digest. `document_metadata_sha256` owns the
canonical hash of every `DocumentRecord` field, including storage key, creator,
creation/removal timestamps, retention and linkage. Aware timestamps normalize
to UTC. Content hashes are versions of original bytes; no integer document
revision or signedness is invented.

`DocumentEvidenceRetentionPersistence.retain_verified_evidence` is implemented
by `PostgresDocumentEvidenceRetention`, registered through
`document_evidence_retention_adapter`. It must receive the RF caller's existing
transaction connection. `documents.retain_verified_rf_evidence_v1` checks the
accepted owner, locks exact same-company/document-year metadata, verifies actual
status/hash/length, registers a deterministic per-source/document reference and
returns the complete locked row. The Documents adapter hashes that record and
calls `documents.assert_retained_metadata_v1` while the lock is held. A mismatch
aborts the SQL transaction, even if a caller mistakenly catches its exception.
No RF adapter reads Documents tables directly.

RF source insertion and every referenced original must commit in that same
transaction. The new SQL API accepts only RF year sources and independent
register observations. It preserves attached/stored/unsigned/owner-attested
statuses unchanged. This retention operation is not independent-provenance
attestation and cannot make filing-generated evidence suitable for register
capture. Those source rules remain with the source owner and trusted workflow.
Corrections create additional reference sets; original references are retained.
Rollback revokes new capture calls while preserving all registry rows, accepted
statuses and existing document-removal guards. Metadata row locks close the
verified-metadata-to-source-capture gap; no provider-object lock or external
cross-capability lease is claimed.

The removal guard uses Ledger's published `has_document_memo_reference_v1`
lookup with the document's company identity. It does not depend on the retired
`public.ledger_entries` predecessor relation. The additive Documents migration
changes only that predicate, preserving every RF, Tax, Accounts and other
reference branch and the existing function privileges. Replay it after a frozen
RF cutover that restores the historical guard. Rollback retains the safety
correction because restoring the retired-table read would break removal checks.
