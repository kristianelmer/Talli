# Shareholder register filing presentation

The feature uses the generated API client to present RF-1086 previews, review,
simulation, approvals and retained production history. Python owns validation,
payloads, confirmation gates and lifecycle decisions. Authority credentials and
business persistence stay behind the backend boundary.

The two shipped v1 Send and recovery operation names remain unchanged.

<!-- architecture-inventory
{"publicEntryPoints":["@/features/shareholder-register-filing","apps/web/features/shareholder-register-filing","apps/web/features/shareholder-register-filing/index.ts"],"routes":["/filing/aksjonaerregisteroppgaven/source","/filing/aksjonaerregisteroppgaven/register"],"apiOperations":["legacyRf1086ReconcileFeedback","legacyRf1086SendApprovedFiling","rf1086AcknowledgeReviewComment","rf1086AddReviewComment","rf1086ApproveProduction","rf1086ApproveSourceProduction","rf1086CaptureRegisterObservation","rf1086CaptureYearSource","rf1086ConfirmFilingPermission","rf1086ConfirmSimulation","rf1086GeneratePreview","rf1086GenerateSourcePreview","rf1086GetArchiveSource","rf1086GetProductionArchiveSource","rf1086ListRegisterObservations","rf1086PrepareSourceProductionReview","rf1086Preview","rf1086ReadCurrentYearSource","rf1086ReadSourceDocument","rf1086ReadSourceIntakeBasis","rf1086ReadSourcePreview","rf1086RecordOverride","rf1086RecordTestEvidence","rf1086Workspace","rf1086SendSourceProduction","rf1086ReadSourceProductionPosition"],"dependencies":[]}
-->

`rf1086GetArchiveSource` preserves the original archive extent for one company/year, including company-wide comments and permissions. `rf1086GetProductionArchiveSource` adds immutable approval, submission, journal and receipt evidence. The web falls back to the original contract only when the expanded endpoint returns 404; production evidence remains explicitly unavailable during that overlap, never an assumed empty history. Other errors block export.


The source intake route reads the current company/year basis and retained source
through authenticated generated transport. Only an explicit `currentSource:null`
means no retained source. Scope mismatches, malformed responses and backend
failures stay failures; the feature does not infer an empty year or omit
cross-year Governance history. Current-source receipts and editable drafts must
agree on company, year, predecessor identity and digest, with review confirmations
reset for a new owner review.

Year-source and register-observation capture require the caller's stable attempt
key. Transport preserves decimal strings, civil event timestamps, original
source-document years and caller keys without generating replacements. Preview
creation is a separate deliberate append operation, with no automatic retry or
claimed idempotency guarantee. Preview reads bind company/year/source/preview
identity. The backend retains completeness, validation, evidence verification and
production admission policy; transport does not authorize filing from intake
blockers or preview status. Source error messages use a closed Norwegian mapping
and never echo provider or evidence details.

The independent register route lists retained observations with exact revision,
fact digest, civil event time and original-document roles. Correction drafts bind
the selected receipt and clear all owner confirmations. The transport rejects
scope mismatches and duplicate observations, preserves historical rows, and uses
the backend currentness flag; multiple independent current lineages are allowed.
Reads do not verify original bytes or authorize a corporate event or filing.
Register capture uses the same caller-owned attempt key and a separate closed
error mapping. Only known prewrite refusals allow editing a first failed attempt;
a prior uncertain result must remain attached to its original body and key.

The annual-source preview now presents production approval separately from capture.
The server resolves the exact full-year Billing pilot, then requests the owned RF
review commitment. Blockers are displayed, warning acknowledgements and explicit
confirmation are required, and prior filings can be selected for a reviewed
correction. An uncertain approval keeps the identical command for retry. Approval
does not send; the interface explicitly reports full-year submission unavailable
until its guarded command is implemented. All decisive checks remain in RF.

Full-year archive transport requires complete source-approval lineage, matching
submission claims and a scoped filing head. Company downloads preserve these
records and check each retained source document against the exported Documents
object identity, hash, length, type and status. Missing or changed originals block
export. This does not establish consolidated restore or retention coverage.

Production archive responses also carry the opaque `canonicalArchive` record.
Company downloads preserve it byte-for-byte for Python-owned source and history
verification. The web restore fixture checks its container checksum; it does not
interpret canonical RF facts or grant restore/submission authority.


`sourceOriginals` carries Documents-owned portable records for exact historical
source versions, including prior-year originals. The download preserves these
records verbatim. Web checks only scope, shape and metadata/byte commitments;
Python owns record reconstruction. Restore consistency no longer substitutes the
current-year Documents projection for captured source metadata. Feedback receipt
projection checks still apply. These checks do not hydrate a database or bucket.

V2 `sourceHistoryDocuments` declares all captured document requirements,
including unapproved source versions and independent register observations.
Downloads preserve it with the canonical record and originals. Web verification
compares these technical metadata commitments with the canonical history and
rejects partial projections or missing originals. Python owns source chains,
observation corrections, capture replay identities and filing policy. Existing v1
archives remain readable without claiming complete source-history coverage.

Full-year send uses the generated `rf1086SendSourceProduction` operation with approval/manifest/predecessor identity only. The transport never automatically retries. Unknown and blocked outcomes retain distinct owner-facing messages and require stored-status inspection. Production authorization remains backend-owned.

The source screen reads retained dispatch position and its exact approved preview before a separate, explicit send. Each send attempt clears the control until a fresh status read. Uncertain or blocked positions expose no send control; confirmed positions use read-only feedback recovery and their own document links. Current source-read failures do not hide retained approvals. Server actions authenticate and check scoped retained identity; all consequential policy stays in RF.
