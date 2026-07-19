export const COMPANY_DOCUMENTS_BUCKET = "company-documents";
export const MAX_DOCUMENT_UPLOAD_BYTES = 10 * 1024 * 1024;

export function validateDocumentUpload(input: {
  name: string;
  contentType: string;
  size: number;
  header: Uint8Array;
}) {
  const name = input.name.split(/[\\/]/).pop()?.trim() ?? "";
  if (!name || !name.toLocaleLowerCase("en-US").endsWith(".pdf")) {
    throw new Error("Dokumentet må være en PDF-fil.");
  }
  if (!Number.isInteger(input.size) || input.size <= 0) {
    throw new Error("PDF-filen er tom eller har ugyldig størrelse.");
  }
  if (input.size > MAX_DOCUMENT_UPLOAD_BYTES) {
    throw new Error("PDF-filen kan ikke være større enn 10 MB.");
  }
  if (!['application/pdf', 'application/octet-stream', ''].includes(input.contentType)) {
    throw new Error("Dokumentet må være en PDF-fil.");
  }
  const signature = new TextDecoder("ascii").decode(input.header.slice(0, 5));
  if (signature !== "%PDF-") {
    throw new Error("Filen er ikke en gyldig PDF.");
  }
  return { name, contentType: "application/pdf" as const, size: input.size };
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

export function rf1086FeedbackStorageKey(companyId: string, submissionId: string, sha256: string) {
  return `authority-feedback/${companyId}/${submissionId}/${sha256}`;
}

export function rf1086FeedbackFileName(contentType: string, sha256: string) {
  const extension = contentType === "application/xml" || contentType === "text/xml"
    ? "xml"
    : contentType === "application/pdf"
      ? "pdf"
      : contentType === "text/plain"
        ? "txt"
        : "bin";
  return `authority-feedback-${sha256.slice(0, 12)}.${extension}`;
}
