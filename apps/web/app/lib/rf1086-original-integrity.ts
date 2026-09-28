import { createHash } from "node:crypto";

const record = (value: any): value is Record<string, any> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: any) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const keys = (value: Record<string, any>, expected: string[]) => Object.keys(value).sort().join(",") === expected.sort().join(",");
const exactInstant = (value: any): string | null => {
  if (typeof value !== "string") return null;
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return null;
  const seconds = Date.parse(match[1] + match[3]);
  return Number.isFinite(seconds) ? (BigInt(seconds) * BigInt(1_000_000) + BigInt((match[2] ?? "").padEnd(9, "0"))).toString() : null;
};
const identity = (row: any) => JSON.stringify([row.documentId, row.companyId, row.sourceIncomeYear,
  row.metadataSha256, row.contentSha256, row.byteLength]);
const commitment = (row: any) => JSON.stringify([identity(row), row.contentVersionSha256,
  row.documentType, row.integrityStatus, new Date(row.createdAt).toISOString()]);

function historyCommitmentsMatch(rf: Record<string, any>, documents: any[]): boolean {
  const envelope = JSON.parse(rf.canonicalArchive);
  if (!record(envelope) || !["rf1086-production-archive-v2", "rf1086-production-archive-v3"].includes(envelope.codec)
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
      if (["rf1086-production-archive-v2", "rf1086-production-archive-v3"].includes(codec)) return false;
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

/** Verify captured feedback bindings and their portable original bytes. */
export function rf1086FeedbackOriginalsMatch(rf: Record<string, any>): boolean {
  try {
    const artifacts = rf.feedbackArtifacts ?? [], originals = rf.feedbackOriginals ?? [];
    if (!Array.isArray(artifacts) || !Array.isArray(originals)) return false;
    if (artifacts.some(row => !record(row)) || new Set(artifacts.map(row => row.id)).size !== artifacts.length) return false;
    const bindingFields = ["originalId", "originalMetadataSha256", "originalSourceIncomeYear", "originalRetainedAt"];
    if (artifacts.some(row => bindingFields.some(key => row[key] != null)
        && !bindingFields.every(key => row[key] != null))) return false;
    const bound = artifacts.filter(row => row?.originalId != null);
    if (bound.length !== originals.length) return false;
    let captured: any[] = [], submissions: any[] = [];
    if (rf.canonicalArchive != null) {
      const envelope = JSON.parse(rf.canonicalArchive);
      if (!record(envelope) || !keys(envelope, ["codec", "snapshotText", "sha256"])
          || typeof envelope.snapshotText !== "string" || digest(envelope.snapshotText) !== envelope.sha256
          || !["rf1086-production-archive-v1", "rf1086-production-archive-v2", "rf1086-production-archive-v3"].includes(envelope.codec)
          || (bound.length > 0 && envelope.codec !== "rf1086-production-archive-v3")) return false;
      const snapshot = JSON.parse(envelope.snapshotText);
      if (snapshot?.record !== "Rf1086ArchiveSnapshot" || !Array.isArray(snapshot.fields?.feedback_artifacts)
          || !Array.isArray(snapshot.fields?.production_submissions)) return false;
      captured = snapshot.fields.feedback_artifacts;
      submissions = snapshot.fields.production_submissions;
      if (captured.length !== artifacts.length) return false;
      for (const artifact of artifacts) {
        const matches = captured.filter(row => row?.record === "Rf1086ArchiveFeedbackArtifactRecord" && row.fields?.id === artifact.id);
        if (matches.length !== 1) return false;
        const fields = matches[0].fields;
        for (const [wire, stored] of [["companyId", "company_id"], ["submissionId", "submission_id"],
          ["documentId", "document_id"], ["contentType", "content_type"], ["byteLength", "byte_length"], ["sha256", "sha256"],
          ["classification", "classification"], ["authorityReference", "authority_reference"],
          ["originalId", "original_id"], ["originalMetadataSha256", "original_metadata_sha256"],
          ["originalSourceIncomeYear", "original_source_income_year"]]) {
          if ((artifact[wire] ?? null) !== (fields[stored] ?? null)) return false;
        }
        if (artifact.originalId != null && (exactInstant(artifact.originalRetainedAt) === null
            || exactInstant(artifact.originalRetainedAt) !== exactInstant(fields.original_retained_at))) return false;
        if (exactInstant(artifact.retrievedAt) === null
            || exactInstant(artifact.retrievedAt) !== exactInstant(fields.retrieved_at)) return false;
      }
    } else if (bound.length) return false;
    const expected = [];
    for (const artifact of bound) {
      const matches = originals.filter(row => row?.documentId === artifact.documentId);
      if (matches.length !== 1 || artifact.originalSourceIncomeYear !== rf.incomeYear) return false;
      const envelope = JSON.parse(matches[0].canonicalOriginal), document = JSON.parse(envelope.documentText);
      const submission = submissions.find(row => row?.record === "Rf1086ProductionSubmissionRecord" && row.fields?.id === artifact.submissionId);
      if (envelope.receipt?.originalId !== artifact.originalId
          || exactInstant(envelope.receipt?.retainedAt) === null
          || exactInstant(envelope.receipt.retainedAt) !== exactInstant(artifact.originalRetainedAt)
          || document.content_type !== artifact.contentType
          || document.linked_to !== "production_filing_submission:" + artifact.submissionId
          || document.created_by?.kind !== "USER" || document.created_by?.subject?.value !== submission?.fields?.user_id) return false;
      expected.push({ documentId: artifact.documentId, companyId: artifact.companyId,
        sourceIncomeYear: artifact.originalSourceIncomeYear, metadataSha256: artifact.originalMetadataSha256,
        contentSha256: artifact.sha256, byteLength: artifact.byteLength, contentVersionSha256: artifact.sha256,
        documentType: "authority_feedback", integrityStatus: "stored", createdAt: document.created_at });
    }
    return rf1086SourceOriginalsMatch({ companyId: rf.companyId,
      sourceApprovalLineage: [{ source: { command: { documents: expected } } }], sourceOriginals: originals });
  } catch { return false; }
}
