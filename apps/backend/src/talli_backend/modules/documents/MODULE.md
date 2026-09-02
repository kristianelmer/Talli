# Documents backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["public.documents"],"ports":["DocumentObjectStorage","DocumentsAuthorization","DocumentsPersistence"],"publicEntryPoints":["talli_backend.modules.documents.public"]}
-->

`documents` owns accounting-document validation, the `public.documents` metadata
lifecycle, the private `company-documents` bucket, integrity hashes, retention,
safe removal and restoration, and document-only backup projections. Uploads are
staged before the backend issues one exact signed object transfer. Finalization
downloads and verifies the stored PDF before recording its byte length and
SHA-256 digest. Preview and download transfers recheck those immutable facts;
download additionally requires AAL2.

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
