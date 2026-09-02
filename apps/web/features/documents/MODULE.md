# Documents web feature

<!-- architecture-inventory
{"apiOperations":["documentsBackupProjection","documentsBeginUpload","documentsCreateTransfer","documentsFinalizeUpload","documentsList","documentsRemove"],"dependencies":[],"publicEntryPoints":["@/features/documents","apps/web/features/documents","apps/web/features/documents/index.ts"],"routes":["/documents","/documents/[documentId]/download","/documents/[documentId]/preview"]}
-->

## Purpose and boundary

This feature carries document commands and projections through the committed
generated API client. The backend owns file validation, storage-key derivation,
staging, finalization, quarantine, integrity hashes, evidence-link checks,
retention metadata, authorization, step-up, and backup projection. The web may
upload exactly one file with the single-object signed transfer issued for a
staged document; it never selects a bucket path or lifecycle state itself.

Presentation mapping preserves the temporary snake-case shape consumed by the
existing owner UI. That mapping is not a persistence contract. No caller may
query `documents`, invoke document lifecycle RPCs, create broad bucket URLs, or
download storage objects directly.
