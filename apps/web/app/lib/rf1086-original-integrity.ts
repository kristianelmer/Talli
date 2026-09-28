import { createHash } from "node:crypto";

const record = (value: any): value is Record<string, any> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: any) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const keys = (value: Record<string, any>, expected: string[]) => Object.keys(value).sort().join(",") === expected.sort().join(",");
const identity = (row: any) => JSON.stringify([row.documentId, row.companyId, row.sourceIncomeYear,
  row.metadataSha256, row.contentSha256, row.byteLength]);
const commitment = (row: any) => JSON.stringify([identity(row), row.contentVersionSha256,
  row.documentType, row.integrityStatus, new Date(row.createdAt).toISOString()]);

function historyCommitmentsMatch(rf: Record<string, any>, documents: any[]): boolean {
  const envelope = JSON.parse(rf.canonicalArchive);
  if (!record(envelope) || envelope.codec !== "rf1086-production-archive-v2"
      || !keys(envelope, ["codec", "snapshotText", "sha256"])
      || typeof envelope.snapshotText !== "string" || digest(envelope.snapshotText) !== envelope.sha256) return false;
  const snapshot = JSON.parse(envelope.snapshotText);
  if (snapshot?.record !== "Rf1086ArchiveSnapshot"
      || snapshot.fields?.source_history?.record !== "Rf1086ArchiveSourceHistory") return false;
  const history = snapshot.fields.source_history.fields;
  const expected = new Set<string>();
  // Compare only captured document commitments with their transport projection.
  // Python still owns decoding the RF history, source chains and filing policy.
  for (const [field, kind, documentKind] of [
    ["year_sources", "Rf1086YearSourceSnapshot", "Rf1086YearDocumentEvidence"],
    ["register_observations", "Rf1086RegisterObservationSnapshot", "Rf1086RegisterDocumentEvidence"],
  ]) {
    if (!Array.isArray(history?.[field])) return false;
    for (const entry of history[field]) {
      if (entry?.record !== kind || !Array.isArray(entry.fields?.command?.fields?.documents)) return false;
      for (const document of entry.fields.command.fields.documents) {
        if (document?.record !== documentKind) return false;
        const f = document.fields;
        if (f?.company_id?.record !== "CompanyId" || f?.source_income_year?.record !== "IncomeYear") return false;
        expected.add(commitment({ documentId: f.document_id, companyId: f.company_id.fields.value,
          sourceIncomeYear: f.source_income_year.fields.value, metadataSha256: f.metadata_sha256,
          contentSha256: f.content_sha256, byteLength: f.byte_length, contentVersionSha256: f.content_version_sha256,
          documentType: f.document_type, integrityStatus: f.integrity_status, createdAt: f.created_at.datetime }));
      }
    }
  }
  const actual = new Set(documents.map(commitment));
  return actual.size === expected.size && [...expected].every(value => actual.has(value));
}

/** Verify transport commitments only; Documents' Python codec owns reconstruction. */
export function rf1086SourceOriginalsMatch(rf: Record<string, any>): boolean {
  try {
    const lines = rf.sourceApprovalLineage ?? [];
    if (!Array.isArray(lines)) return false;
    const expected = new Map<string, any>();
    const history = rf.sourceHistoryDocuments;
    if (history != null && (!Array.isArray(history) || !historyCommitmentsMatch(rf, history))) return false;
    if (history == null && typeof rf.canonicalArchive === "string") {
      let codec;
      try { codec = JSON.parse(rf.canonicalArchive)?.codec; } catch { /* The separate canonical check diagnoses malformed v1. */ }
      if (codec === "rf1086-production-archive-v2") return false;
    }
    const groups = lines.map(line => line?.source?.command?.documents);
    if (history != null) groups.push(history);
    for (const documents of groups) {
      if (!Array.isArray(documents)) return false;
      for (const source of documents) {
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
