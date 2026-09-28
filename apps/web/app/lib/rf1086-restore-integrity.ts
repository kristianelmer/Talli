import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";

const record = (value: any): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: any) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const digest = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");
const instant = (value: any) => typeof value === "string"
  && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

// Technical consistency checks on retained evidence. This neither reconstructs
// RF business facts nor replaces Python validation or a database/object restore.
export function rf1086SourceRestoreFailures(rf: Record<string, any>, objects: any[]) {
  const failures = new Set<string>();
  const fail = (code: string) => failures.add(`rf1086_source_${code}`);
  const scoped = (row: any) => record(row) && row.companyId === rf.companyId
    && Number.isInteger(row.incomeYear) && row.incomeYear === rf.incomeYear;
  const approvals = rf.approvals.filter((row: any) => row.caseProfile === "rf1086_full_year_v1");
  const submissions = rf.productionSubmissions.filter((row: any) => row.caseProfile === "rf1086_full_year_v1");
  if (approvals.length || rf.canonicalArchive != null) {
    try {
      if (typeof rf.canonicalArchive !== "string") throw new Error("missing");
      const envelope = JSON.parse(rf.canonicalArchive);
      if (!record(envelope) || envelope.codec !== "rf1086-production-archive-v1"
          || typeof envelope.snapshotText !== "string" || !hash(envelope.sha256)
          || digest(envelope.snapshotText) !== envelope.sha256
          || Object.keys(envelope).sort().join(",") !== "codec,sha256,snapshotText") throw new Error("invalid");
    } catch {
      fail("canonical_record_invalid");
    }
  }
  const lineage = rf.sourceApprovalLineage ?? [];
  const claims = rf.sourceSubmissionClaims ?? [];
  if (!Array.isArray(lineage) || !Array.isArray(claims)
      || lineage.some(row => !record(row)) || claims.some(row => !record(row))) {
    fail("evidence_shape_invalid");
    return [...failures];
  }
  if (lineage.length !== approvals.length
      || new Set(lineage.map(row => row.approvalId)).size !== lineage.length) fail("approval_lineage_mismatch");
  if (claims.length !== submissions.length
      || new Set(claims.map(row => row.submissionId)).size !== claims.length
      || new Set(claims.map(row => row.approvalId)).size !== claims.length) fail("claim_mismatch");
  const objectMap = new Map(objects.filter(record).map(row => [row.documentId, row]));
  if (lineage.length && (objectMap.size !== objects.length)) fail("document_object_mismatch");
  for (const line of lineage) {
    const approval = approvals.find((row: any) => row.id === line.approvalId);
    const receipt = line.source?.receipt, command = line.source?.command;
    const preview = line.sourcePreview, bridge = line.bridge;
    if (!approval || !scoped(line) || !scoped(receipt) || !scoped(command)
        || !scoped(preview) || !scoped(bridge) || !record(command.case) || !record(command.paidIn)
        || !hash(line.sourceSha256) || !hash(line.payloadSha256)
        || !hash(line.manifestSha256) || !hash(line.reviewSha256)
        || approval.previewId !== line.previewId || approval.approvedBy !== line.approvedBy
        || approval.manifestHash !== line.manifestSha256 || approval.payloadHash !== line.payloadSha256
        || [receipt, preview, bridge].some(row => row.sourceId !== line.sourceId || row.sourceSha256 !== line.sourceSha256)
        || preview.previewId !== line.previewId || bridge.previewId !== line.previewId
        || bridge.payloadSha256 !== line.payloadSha256 || bridge.createdBy !== line.approvedBy) {
      fail("approval_lineage_mismatch");
      continue;
    }
    let manifest: any;
    try {
      if (typeof line.manifestText !== "string" || typeof line.reviewText !== "string"
          || digest(line.manifestText) !== line.manifestSha256 || digest(line.reviewText) !== line.reviewSha256) {
        throw new Error("commitment");
      }
      manifest = JSON.parse(line.manifestText);
      if (!record(manifest) || !record(JSON.parse(line.reviewText))
          || !isDeepStrictEqual(manifest, approval.manifest)
          || manifest.review?.sha256 !== line.reviewSha256
          || manifest.source?.id !== line.sourceId || manifest.source?.sha256 !== line.sourceSha256
          || manifest.source?.version !== receipt.version || manifest.source?.caseSha256 !== receipt.caseSha256
          || preview.caseSha256 !== receipt.caseSha256 || manifest.preview?.id !== line.previewId
          || typeof preview.previewText !== "string" || digest(preview.previewText) !== manifest.preview?.reviewTextSha256
          || !scoped(manifest) || manifest.userId !== line.approvedBy
          || manifest.entitlementId !== approval.entitlementId) throw new Error("binding");
    } catch {
      fail("approval_commitment_mismatch");
    }
    // Original XML bytes are preserved, not regenerated with current rules.
    if (record(manifest) && Array.isArray(manifest.documentHashes)) {
      const documents = manifest.documentHashes;
      const underskjema = preview.underskjemaXml;
      if (!record(underskjema) || documents.length !== Object.keys(underskjema).length + 1
          || new Set(documents.filter(record).map(row => row.name)).size !== documents.length
          || documents.some((row: any) => {
            if (!record(row) || !hash(row.sha256) || typeof row.name !== "string") return true;
            const xml = row.name === "hovedskjema" ? preview.hovedskjemaXml
              : row.name.startsWith("underskjema_") ? underskjema[row.shareholderId] : undefined;
            return typeof xml !== "string" || digest(xml) !== row.sha256;
          })) fail("xml_commitment_mismatch");
    } else fail("xml_commitment_mismatch");
    if (!Array.isArray(command.documents) || command.documents.some((source: any) => {
      if (!record(source)) return true;
      const object = objectMap.get(source.documentId);
      return source.companyId !== rf.companyId || !hash(source.contentSha256)
        || !Number.isSafeInteger(source.byteLength) || source.byteLength <= 0
        || !object || object.contentSha256 !== source.contentSha256 || object.byteLength !== source.byteLength
        || object.documentType !== source.documentType || object.status !== source.integrityStatus
        || typeof object.storageKey !== "string" || !object.storageKey || object.removedAt != null;
    })) fail("document_object_mismatch");
  }
  for (const claim of claims) {
    const submission = submissions.find((row: any) => row.id === claim.submissionId);
    const approval = approvals.find((row: any) => row.id === claim.approvalId);
    if (!scoped(claim) || !submission || !approval || !instant(claim.claimedAt)
        || submission.approvalId !== claim.approvalId || approval.manifestHash !== claim.manifestSha256
        || approval.payloadHash !== claim.payloadSha256 || submission.payloadHash !== claim.payloadSha256
        || approval.approvedBy !== claim.claimedBy || submission.submittedBy !== claim.claimedBy
        || submission.supersedesSubmissionId !== claim.predecessorSubmissionId
        || (approval.manifest?.predecessor?.submissionId ?? null) !== claim.predecessorSubmissionId) fail("claim_mismatch");
  }
  const head = rf.submissionHead;
  if (!submissions.length) {
    if (head != null) fail("head_mismatch");
  } else if (!scoped(head) || head.obligation !== "aksjonaerregisteroppgaven" || head.environment !== "production"
      || !instant(head.updatedAt) || !submissions.some((row: any) => row.id === head.submissionId)) {
    fail("head_mismatch");
  } else {
    const rows = new Map<string, any>(rf.productionSubmissions.map((row: any) => [row.id, row]));
    const visited = new Set<string>();
    let id: string | null = head.submissionId;
    while (id != null && rows.has(id) && !visited.has(id)) {
      visited.add(id);
      id = rows.get(id).supersedesSubmissionId;
    }
    if (id != null || visited.size !== rows.size) fail("head_mismatch");
  }
  return [...failures];
}
