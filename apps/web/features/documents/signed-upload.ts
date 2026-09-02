import type {
  DocumentBeginUploadWire,
  DocumentWire,
} from "@talli/talli-api-client";

import {
  beginDocumentUpload,
  finalizeDocumentUpload,
} from "./transport.ts";

export type SignedDocumentUploadPort = {
  upload(input: {
    bucket: string;
    storageKey: string;
    token: string;
    body: Blob | Uint8Array;
    contentType: string;
  }): Promise<{ error: { message: string } | null }>;
};

export async function uploadDocumentObject(input: {
  accessToken: string;
  command: DocumentBeginUploadWire;
  body: Blob | Uint8Array;
  port: SignedDocumentUploadPort;
  beginIdempotencyKey: string;
  finalizeIdempotencyKey: string;
  requestId?: string;
}): Promise<DocumentWire> {
  const transfer = await beginDocumentUpload(
    input.accessToken,
    input.command,
    input.beginIdempotencyKey,
    input.requestId,
  );
  const upload = await input.port.upload({
    bucket: transfer.bucket,
    storageKey: transfer.storageKey,
    token: transfer.token,
    body: input.body,
    contentType: input.command.contentType,
  });
  if (upload.error) {
    throw new Error(`Signed document upload failed: ${upload.error.message}`);
  }
  return finalizeDocumentUpload(
    input.accessToken,
    input.command.documentId,
    input.finalizeIdempotencyKey,
    input.requestId,
  );
}
