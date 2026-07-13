export const COMPANY_DOCUMENTS_BUCKET = "company-documents";
export const MAX_DOCUMENT_UPLOAD_BYTES = 6 * 1024 * 1024;

export type ValidatedDocumentUpload = {
  contentType: "application/pdf" | "image/png" | "image/jpeg" | "text/csv";
  fileName: string;
};

export class DocumentUploadValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "DocumentUploadValidationError";
    this.code = code;
  }
}

function startsWithBytes(bytes: Uint8Array, signature: number[]) {
  return signature.every((value, index) => bytes[index] === value);
}

export async function validateDocumentUpload(file: File): Promise<ValidatedDocumentUpload> {
  if (file.size === 0) {
    throw new DocumentUploadValidationError("Dokumentet er tomt.", "empty_document");
  }
  if (file.size > MAX_DOCUMENT_UPLOAD_BYTES) {
    throw new DocumentUploadValidationError("Dokumentet kan ikke være større enn 6 MB.", "document_too_large");
  }

  const fileName = file.name
    .normalize("NFKC")
    .replace(/[\u0000-\u001f\u007f]/gu, " ")
    .trim();
  if (!fileName || fileName.length > 255) {
    throw new DocumentUploadValidationError("Dokumentnavnet er ugyldig.", "invalid_document_name");
  }

  const extension = fileName.toLowerCase().match(/\.[a-z0-9]+$/u)?.[0] ?? "";
  const bytes = new Uint8Array(await file.slice(0, 4096).arrayBuffer());
  if (extension === ".pdf" && startsWithBytes(bytes, [0x25, 0x50, 0x44, 0x46, 0x2d])) {
    return { contentType: "application/pdf", fileName };
  }
  if (extension === ".png" && startsWithBytes(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
    return { contentType: "image/png", fileName };
  }
  if ([".jpg", ".jpeg"].includes(extension) && startsWithBytes(bytes, [0xff, 0xd8, 0xff])) {
    return { contentType: "image/jpeg", fileName };
  }
  if (extension === ".csv" && !bytes.includes(0)) {
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      return { contentType: "text/csv", fileName };
    } catch {
      // Fall through to the stable validation error below.
    }
  }

  throw new DocumentUploadValidationError(
    "Dokumentet må være en ekte PDF-, PNG-, JPEG- eller UTF-8 CSV-fil.",
    "unsupported_document_format",
  );
}

export function documentStorageKey(companyId: string, incomeYear: number, documentId: string, fileName: string) {
  const safeName = fileName
    .normalize("NFKD")
    .split(/[\\/]/)
    .pop()!
    .replace(/[^\w.\-]+/g, "-")
    .replace(/^\.+/, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 120);
  return `${companyId}/${incomeYear}/${documentId}/${safeName || "document"}`;
}
