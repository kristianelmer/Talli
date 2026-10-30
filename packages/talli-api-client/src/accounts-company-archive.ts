/** Byte, scope and enumeration checks. Python owns journal interpretation. */
import type {AccountsCompanyArchiveWire} from "./generated/client.ts";

const object = (v: any) => v !== null && typeof v === "object" && !Array.isArray(v);
const keys = (v: any, expected: string[]) => object(v) && Object.keys(v).sort().join(",") === [...expected].sort().join(",");
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/u.test(v);
const instant = (v: any) => typeof v === "string" && Number.isFinite(Date.parse(v)) ? Date.parse(v) : NaN;
const families = ["previews","submissions","overrides","review_comments","permissions","test_evidence"];
const codecs = new Set(["annual-accounts-delivery-review-v1","annual-accounts-finite-admission-v1",
  "annual-accounts-delivery-intent-v1","annual-accounts-delivery-completion-v1","annual-accounts-delivery-observation-v1",
  "annual-accounts-delivery-frame-v1","annual-accounts-correction-parent-admission-v1","annual-accounts-correction-parent-attempt-v1",
  "annual-accounts-correction-parent-observation-v1","annual-accounts-correction-parent-frame-v1"]);

/** Synchronous server/restore form accepts its platform's SHA-256 primitive. */
export function inspectAccountsCompanyArchive(value: AccountsCompanyArchiveWire, companyId: string, incomeYear: number,
  digest: (raw: string) => string | undefined) {
  const fail = () => { throw new Error("Accounts company archive is incomplete or changed."); };
  if (!keys(value,["companyId","incomeYear","codec","canonicalJson","sha256","sourceSha256","draftCount","eventCount","originalCount"])
      || value.companyId !== companyId || value.incomeYear !== incomeYear || value.codec !== "annual-accounts-company-year-archive-v1"
      || typeof value.canonicalJson !== "string" || new TextEncoder().encode(value.canonicalJson).length > 192*1024*1024
      || !hash(value.sha256) || !hash(value.sourceSha256) || digest(value.canonicalJson) !== value.sha256) fail();
  const source = JSON.parse(value.canonicalJson);
  if (!keys(source,["codec","companyId","incomeYear","contractVersion","asOf","sourceSha256","rows","coverage","drafts","events"])
      || source.codec !== value.codec || source.companyId !== companyId || source.incomeYear !== incomeYear
      || !["annual-accounts-source-v3","annual-accounts-source-v4"].includes(source.contractVersion)
      || source.sourceSha256 !== value.sourceSha256 || !Number.isFinite(instant(source.asOf)) || !keys(source.rows,families)
      || !Array.isArray(source.drafts) || source.drafts.length > 64 || value.draftCount !== source.drafts.length
      || !Array.isArray(source.events) || source.events.length > 10000 || value.eventCount !== source.events.length) fail();
  const proof = source.coverage;
  if (!object(proof) || proof.companyId !== companyId || proof.incomeYear !== incomeYear
      || proof.scope !== "talli_recorded_annual_accounts" || !["cutover","contracted"].includes(proof.phase)
      || proof.contractVersion !== source.contractVersion || proof.declaredExtentValid !== false
      || proof.deliveryDraftCount !== value.draftCount || proof.deliveryEventCount !== value.eventCount
      || !keys(proof.deliveryDraftDigests,source.drafts.map((row: any) => JSON.parse(row.canonicalJson).draft.filing_id))
      || !keys(proof.deliveryEventDigests,source.events.map((row: any) => String(row.sequence)))
      || proof.deliveryEventCodecVersion !== (source.contractVersion === "annual-accounts-source-v4" ? "annual-accounts-delivery-events-v2" : "annual-accounts-delivery-events-v1")
      || ["inventoryValid","quarantineClear","sourceRowsValid","legacyFencesValid","modeChecksValid","declaredDeliveryExtentValid",
        "deliveryArchiveTrackingValid","deliveryImmutableValid","deliveryKeysValid","deliveryEventContractValid"].some(key => proof[key] !== true)) fail();
  const legacy = new Map([["previews","filing_previews"],["submissions","filing_submissions"],["overrides","filing_overrides"],
    ["review_comments","filing_review_comments"],["permissions","authority_permissions"],["test_evidence","authority_test_runs"]]);
  for (const key of families) {
    const rows = source.rows[key];
    if (!Array.isArray(rows) || new Set(rows.map((row: any) => row.id)).size !== rows.length
      || rows.some((row: any) => !object(row) || row.company_id !== companyId || typeof row.id !== "string"
        || row.income_year != null && row.income_year !== incomeYear)
      || proof.familyCounts?.[legacy.get(key)!] !== rows.length || !hash(proof.familyDigests?.[legacy.get(key)!])) fail();
  }
  const drafts = new Map<string, any>();
  for (const row of source.drafts) {
    if (!keys(row,["canonicalJson","sha256","recordedAt"]) || !hash(row.sha256) || typeof row.canonicalJson !== "string"
      || digest(row.canonicalJson) !== row.sha256 || !(instant(row.recordedAt) <= instant(source.asOf))) fail();
    const root = JSON.parse(row.canonicalJson), draft = root.draft;
    if (!keys(root,["version","draft"]) || root.version !== "annual-accounts-delivery-draft-v1" || !object(draft)
      || typeof draft.filing_id !== "string" || drafts.has(draft.filing_id) || draft.source?.company_id?.value !== companyId
      || draft.source?.income_year?.value !== incomeYear || draft.prepared_by?.kind !== "USER" || typeof draft.prepared_by?.subject?.value !== "string"
      || proof.deliveryDraftDigests[draft.filing_id] !== row.sha256) fail();
    drafts.set(draft.filing_id,{...row,actor:draft.prepared_by.subject.value});
  }
  let previous = 0, time = -Infinity, originals = 4*value.draftCount;
  const seen = new Set<string>();
  for (const row of source.events) {
    if (!keys(row,["sequence","canonicalJson","sha256","recordedAt"]) || !Number.isSafeInteger(row.sequence) || row.sequence <= previous
      || !hash(row.sha256) || seen.has(row.sha256) || typeof row.canonicalJson !== "string" || digest(row.canonicalJson) !== row.sha256
      || proof.deliveryEventDigests[String(row.sequence)] !== row.sha256 || !(time <= instant(row.recordedAt) && instant(row.recordedAt) <= instant(source.asOf))) fail();
    const root = JSON.parse(row.canonicalJson), record = root.record, binding = record?.binding, draft = drafts.get(binding?.filing_id);
    if (!keys(root,["version","record"]) || !codecs.has(root.version) || !draft || binding.company_id?.value !== companyId
      || binding.income_year?.value !== incomeYear || binding.actor_id?.kind !== "USER" || binding.actor_id?.subject?.value !== draft.actor
      || binding.draft_sha256 !== draft.sha256 || !(instant(draft.recordedAt) <= instant(row.recordedAt))) fail();
    if (root.version.startsWith("annual-accounts-correction-") && source.contractVersion !== "annual-accounts-source-v4") fail();
    if (["annual-accounts-delivery-observation-v1","annual-accounts-correction-parent-observation-v1"].includes(root.version)
      && record.original?.body_base64 != null) originals++;
    originals++; seen.add(row.sha256); previous = row.sequence; time = instant(row.recordedAt);
  }
  if (value.originalCount !== originals || !Number.isSafeInteger(value.originalCount)) fail();
  return source;
}

export async function verifyAccountsCompanyArchive(value: AccountsCompanyArchiveWire, companyId: string, incomeYear: number) {
  if (typeof value?.canonicalJson !== "string" || value.canonicalJson.length > 192*1024*1024) throw new Error("Accounts archive size is invalid.");
  const source = JSON.parse(value.canonicalJson), hashes = new Map<string,string>();
  const rows = [...(Array.isArray(source.drafts) ? source.drafts : []),...(Array.isArray(source.events) ? source.events : [])];
  if (rows.length > 10064) throw new Error("Accounts archive enumeration exceeds its bound.");
  for (const raw of [value.canonicalJson,...rows.map(row => row?.canonicalJson)]) {
    if (typeof raw !== "string") throw new Error("Accounts archive bytes are missing.");
    hashes.set(raw,Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw)))).map(byte => byte.toString(16).padStart(2,"0")).join(""));
  }
  inspectAccountsCompanyArchive(value,companyId,incomeYear,raw => hashes.get(raw));
  return value;
}
