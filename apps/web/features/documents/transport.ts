import {
  createTalliApiClient,
  type DocumentBackupProjectionWire,
  type DocumentBeginUploadWire,
  type DocumentListWire,
  type DocumentRemovalRequestWire,
  type DocumentTransferKind,
  type DocumentTransferWire,
  type DocumentUploadTransferWire,
  type DocumentWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(15_000) };
}

function mutation(idempotencyKey: string, requestId?: string) {
  return { ...request(requestId), idempotencyKey };
}

export function listDocuments(
  accessToken: string,
  companyId: string,
  requestId?: string,
): Promise<DocumentListWire> {
  return client(accessToken).documentsList({ companyId, ...request(requestId) });
}

export function beginDocumentUpload(
  accessToken: string,
  command: DocumentBeginUploadWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<DocumentUploadTransferWire> {
  return client(accessToken).documentsBeginUpload(
    command,
    mutation(idempotencyKey, requestId),
  );
}

export function finalizeDocumentUpload(
  accessToken: string,
  documentId: string,
  idempotencyKey: string,
  requestId?: string,
): Promise<DocumentWire> {
  return client(accessToken).documentsFinalizeUpload(
    documentId,
    mutation(idempotencyKey, requestId),
  );
}

export function createDocumentTransfer(
  accessToken: string,
  documentId: string,
  kind: DocumentTransferKind,
  idempotencyKey: string,
  requestId?: string,
): Promise<DocumentTransferWire> {
  return client(accessToken).documentsCreateTransfer(
    documentId,
    { kind },
    mutation(idempotencyKey, requestId),
  );
}

export function removeDocument(
  accessToken: string,
  documentId: string,
  command: DocumentRemovalRequestWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<DocumentWire> {
  return client(accessToken).documentsRemove(
    documentId,
    command,
    mutation(idempotencyKey, requestId),
  );
}

export function loadDocumentBackupProjection(
  accessToken: string,
  companyId: string,
  incomeYear: number,
  requestId?: string,
): Promise<DocumentBackupProjectionWire> {
  return client(accessToken).documentsBackupProjection({
    companyId,
    incomeYear,
    ...request(requestId),
  });
}
