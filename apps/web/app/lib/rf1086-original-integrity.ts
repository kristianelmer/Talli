import { createHash } from "node:crypto";

const record = (value: any): value is Record<string, any> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: any) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const keys = (value: Record<string, any>, expected: string[]) => Object.keys(value).sort().join(",") === expected.sort().join(",");
const identity = (row: any) => JSON.stringify([row.documentId, row.companyId, row.sourceIncomeYear,
  row.metadataSha256, row.contentSha256, row.byteLength]);

/** Verify transport commitments only; Documents' Python codec owns reconstruction. */
export function rf1086SourceOriginalsMatch(rf: Record<string, any>): boolean {
  try {
    const lines = rf.sourceApprovalLineage ?? [];
    if (!Array.isArray(lines)) return false;
    const expected = new Map<string, any>();
    for (const line of lines) {
      if (!Array.isArray(line?.source?.command?.documents)) return false;
      for (const source of line.source.command.documents) {
        if (!record(source) || source.companyId !== rf.companyId || typeof source.documentId !== "string"
            || !hash(source.metadataSha256) || !hash(source.contentSha256)
            || !Number.isSafeInteger(source.sourceIncomeYear) || source.sourceIncomeYear < 2000 || source.sourceIncomeYear > 2100
            || !Number.isSafeInteger(source.byteLength) || source.byteLength < 1 || source.byteLength > 10485760) return false;
        expected.set(identity(source), source);
      }
    }
    const originals = rf.sourceOriginals ?? [];
    if (!Array.isArray(originals) || originals.length !== expected.size) return false;
    const seen = new Set<string>();
    for (const original of originals) {
      if (!record(original) || !keys(original, ["documentId", "companyId", "sourceIncomeYear", "metadataSha256", "contentSha256", "byteLength", "canonicalOriginal"])) return false;
      const key = identity(original), source = expected.get(key);
      if (!source || seen.has(key) || typeof original.canonicalOriginal !== "string"
          || Buffer.byteLength(original.canonicalOriginal, "utf8") > 16 * 1024 * 1024) return false;
      seen.add(key);
      const envelope = JSON.parse(original.canonicalOriginal);
      if (!record(envelope) || !keys(envelope, ["codec", "documentText", "receipt", "contentBase64"])
          || envelope.codec !== "documents-retained-original-v1" || typeof envelope.documentText !== "string"
          || digest(envelope.documentText) !== source.metadataSha256 || !record(envelope.receipt)
          || !keys(envelope.receipt, ["originalId", "documentId", "companyId", "sourceIncomeYear", "metadataSha256", "contentSha256", "byteLength", "retainedAt"])
          || identity(envelope.receipt) !== key || typeof envelope.contentBase64 !== "string") return false;
      const content = Buffer.from(envelope.contentBase64, "base64");
      if (content.toString("base64") !== envelope.contentBase64 || content.length !== source.byteLength
          || digest(content) !== source.contentSha256) return false;
      const document = JSON.parse(envelope.documentText);
      if (!record(document) || document.document_id?.value !== source.documentId || document.company_id?.value !== rf.companyId
          || document.income_year?.value !== source.sourceIncomeYear || document.content_sha256 !== source.contentSha256
          || document.byte_length !== source.byteLength || document.document_type !== source.documentType
          || document.status !== source.integrityStatus || document.removed_at !== null
          || document.content_sha256 !== source.contentVersionSha256
          || !Number.isFinite(Date.parse(document.created_at)) || Date.parse(document.created_at) !== Date.parse(source.createdAt)) return false;
    }
    return true;
  } catch { return false; }
}
