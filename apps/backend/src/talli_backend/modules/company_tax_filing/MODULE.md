# Company Tax

Company Tax owns settlement capture facts and normalization. Ledger owns account selection and posting; Banking owns matching; Documents owns evidence storage. The application workflow composes those public contracts.

The settlement slice #146 is merged. The full filing slice #152 is in progress. Preview normalization preserves the characterized date-shape and binary64 rounding behavior; it does not certify a valid capture date, positive rounded Money, authorization, or available bank link.

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":[],"publicEntryPoints":["talli_backend.modules.company_tax_filing.public"]}
-->

Public entry point: `talli_backend.modules.company_tax_filing.public`. The query `normalize_tax_settlement` accepts `TaxSettlementInput` and returns `NormalizedTaxSettlement` or `TaxSettlementValidationError`. `TaxSettlementKind` and `TaxSettlementDocumentStatus` describe the supported capture vocabulary.

The settlement workflow uses `RecordTaxSettlementCommand`, `validate_new_tax_settlement`, `CompanyTaxError`, `TaxSettlementId`, `BankTransactionReference`, `DocumentReference`, `AccountingEntryReference`, `TaxSettlementPersistence`, `tax_settlement_persistence_adapter`. The port binds to `talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction`.

`company_tax_filing.settlements` retains the thirteen predecessor fields and opaque Ledger, Banking and Documents identifiers. Expansion snapshots and backfills with its writer disabled; the separate cutover artifact locks and reconciles the old source before enabling capture. Settlement integration is complete under #146; full Company Tax stage exit remains subject to #152.

<!-- architecture-inventory
{"ports":["TaxSettlementPersistence"],"ownedTables":["company_tax_filing.settlements"]}
-->

The Archive query preserves all thirteen fields and opaque references in one authorized company/year. Private Documents callbacks disclose only reference existence and follow the active physical source during rollback.

<!-- architecture-inventory
{"ports":["TaxSettlementArchivePersistence"]}
-->

`TaxSettlementArchiveQuery` binds the verified actor, company and year for the preserved source read.

The deterministic filing contracts are `CompanyTaxReturnSource`, `CompanyTaxReturnCandidate`, `AnnualTaxEstimate`, `CompanyTaxReturnDocuments`, `CompanyTaxEnvelopeInput`, `build_company_tax_return`, `estimate_annual_tax`, `render_company_tax_return`, and `render_company_tax_envelope`. Source and candidate mappings are recursively copied and frozen. The named workflow supplies annual and accounting facts through public contracts; calculations perform no I/O. Annual estimate aggregation deliberately differs from filing-payload aggregation, preserving the captured predecessor behavior.

`CompanyTaxEvidenceInput`, `CompanyTaxEvidenceProjection`, and `project_company_tax_evidence` preserve the strict, sanitized TT02 projection. Imported receipt evidence remains pending authority classification. The pure projection does not authorize persistence, certify a provider operation, or substitute for action-time authentication and MFA. The web import routes through FastAPI and the generated client to the owned SQL workflow. Tax production transport remains disabled.

`CompanyTaxValidationSummary` and `summarize_company_tax_validation` preserve bounded validation text, duplicate removal and Norwegian ICU ordering. The pinned Ada URL parser preserves the predecessor WHATWG canonical-URL check. Both dependencies are local deterministic mechanisms; neither performs authority I/O.

`prepare_company_tax_return` returns `PreparedCompanyTaxReturn` only when the characterized payload has no blocking feedback. The existing tax CLI consumes these public contracts in process; its four statutory TypeScript subprocess branches are retired. The annual-accounts subprocess remains until #153.

The #152 expansion in `supabase/contract-migrations/20260914200000_company_tax_return_expand.sql` creates inert filing targets. It copies Tax rows from six shared families under a source lock, pins exact rows/schema/RPC evidence, quarantines ambiguous obligation or relationship provenance, and compares counts and ordered JSONB hashes. During expansion the legacy writer remains authoritative and the inert targets have FORCE RLS and no business policy/grant. Cutover enables only the owned contracts, fences legacy Tax writes and preserves sibling Accounts rows. Existing company, actor and opening-snapshot foreign-key behavior is preserved, while intra-Tax references bind to the new schema. Temporary migration privileges are restored. The explicitly ordered cutover, contract and rollback artifacts are rehearsed locally; complete stage-exit verification remains pending.

<!-- architecture-inventory
{"ownedTables": ["company_tax_filing.filing_previews", "company_tax_filing.filing_submissions", "company_tax_filing.filing_overrides", "company_tax_filing.filing_review_comments", "company_tax_filing.authority_permissions", "company_tax_filing.authority_test_runs"]}
-->

`CompanyTaxWorkspaceQuery`, `CompanyTaxFilingRows`, and `CompanyTaxWorkspacePersistence` publish complete immutable company-scoped filing rows. The public result checks company, year, obligation, duplicate identities and related preview/test evidence. The read-only SQL contracts in `supabase/contract-migrations/20260914201000_company_tax_return_read_contracts.sql` deny access to inert expansion or rolled-back copies; they become available only after the separate canonical cutover. Company-wide test evidence is not a claim of yearly production completeness.

<!-- architecture-inventory
{"ports":["CompanyTaxWorkspacePersistence"]}
-->

The TT02 import accepts immutable raw evidence and obtains company identity from the existing Company Access public contract. `CompanyTaxReturnPersistence` writes the deterministic projection and returns original receipt IDs with a creation flag. The application owns the surrounding transaction and Audit ordering. The import SQL retains all legacy strict payload, attribution, timestamp, hash, content and replay checks, using owned Tax tables and owner decisions from Company Access. Expansion and rollback reject import execution.

<!-- architecture-inventory
{"ports": ["CompanyTaxReturnPersistence"]}
-->

`ImportCompanyTaxReturnEvidence` carries the immutable command. `CompanyTaxCompanyIdentity` carries the authorized identity fact and `ImportedCompanyTaxEvidence` carries `TaxAuthorityEvidenceId`, `TaxFilingSubmissionId` and the creation flag.

The preparation controls preserve the existing normalization, owner confirmation, reviewer acknowledgement and manual evidence behavior. `RecordCompanyTaxOverride`, `AddCompanyTaxReviewComment`, `ConfirmCompanyTaxPermission`, `RecordCompanyTaxTestEvidence`, `CompanyTaxRecordQuery`, `CompanyTaxRecordedResult`, `normalize_company_tax_override`, `normalize_company_tax_review`, `normalize_company_tax_test_evidence`, `TaxFilingRecordId`, `CompanyTaxPreparationPersistence` expose the declared Tax contracts. Company Access retains accepted-role and fresh-MFA policy. A permission flag records the existing owner declaration; it does not activate a provider or submit a filing. Existing web Audit continuations remain outside these formerly single-row operations.

<!-- architecture-inventory
{"ports": ["CompanyTaxPreparationPersistence"]}
-->

`CompanyTaxReadinessIssue` and `assess_company_tax_readiness` preserve Tax's ordered annual readiness issues: selected company/year holding blocks and missing settlement, followed by the existing payload feedback. Annual retains common readiness gates and Billing retains entitlement/refund decisions. `AnnualTaxEstimateSource` carries only the ordered accounting and holding facts actually used by the existing estimate; it introduces no fictitious company or year.

The authenticated `companyTaxPreviewReadiness` and `companyTaxPreviewAnnualEstimate` endpoints authenticate the caller and evaluate supplied immutable facts without business-data reads or persistence. Their company/year labels scope the requested preview; they do not attest stored source completeness, membership in another company, production history, filing permission, or an authority outcome. They preserve the existing cross-company/all-year annual estimate aggregation. JSON facts are bounded to 8 MiB, malformed facts fail validation, and nonfinite estimates are rejected instead of returning an unusable monetary result. The web consumes these previews through the generated client; the separate source contract below publishes current recorded history and the disabled-production gate.

The HTTP assessment boundary validates consumed nested containers and requires a string ledger account. Direct pure/CLI callers additionally preserve ECMAScript Boolean conversion, including truthy empty arrays/objects; these values cannot silently clear a loan block because Python would consider them false. The 45 predecessor Boolean-boundary captures exercise both payload feedback and Tax readiness.


The four filing expansion/read/write artifacts and the source-snapshot contract live in `supabase/contract-migrations/` because their predecessor must already be contracted. `scripts/rehearse-tax-topology.mjs filing-expand` applies all five in dependency order; `filing-contract` then applies `20260914012503_company_tax_return_cutover.sql` and `20260914012930_company_tax_return_contract.sql`. They are not automatic startup migrations.

The cutover locks and positively enumerates all six shared families, recopies the latest Tax rows, reconciles exact counts/hashes and retains Accounts rows. It restores source trigger modes without advancing Archive generations. Static constraints retire old Tax writes; the existing comment FK binds comments to surviving public previews. The old TT02 RPC is first disabled and then dropped. Runtime source access holds a shared migration-state lock; rollback takes the conflicting lock. Stale repeatable-read transactions fail closed. Documents keeps receipt/feedback retention through a Tax-owned boolean contract.

The full rollback restores the latest owned records and exact predecessor RPC permissions, including records created after cutover. It fences retained owned rows, makes the backend source unavailable and preserves Archive generations. Contract-only rollback leaves the owned writer active. The same cutover artifact supports re-cutover after full rollback. Local SQL and transaction-race evidence does not replace the required HTTP, browser and full release gates.


The predecessor web Tax calculation, XML/envelope, evidence-projection and estimate files are removed. Tax-only helpers are also removed from the shared web authority-evidence file. The remaining Annual Accounts and shared definitions are unchanged. Existing JavaScript cross-output fixtures use a fixed test-only driver of these public Python contracts; no production TypeScript Tax implementation remains.


`CompanyTaxAuthority` is the outbound test-authority port, registered through `company_tax_authority_adapter` to `talli_backend.adapters.company_tax_authority.CompanyTaxTransport`. Its fixed TT02 adapter preserves the existing endpoint, response-validation and redaction mechanics. `CompanyTaxReturnAuthorityError` preserves the sanitized failure shape. `wait_for_company_tax_validation`, `wait_for_company_tax_feedback` and `wait_for_company_tax_clean_envelope` own the existing retry, terminal-status and timeout decisions. The sleep mechanism is supplied by the caller. There is no human-confirmation operation on the port, and production transport remains disabled.

The shared `authority_tools._filing.FixedTransport` and parsing helpers remain the single canonical technical implementation also used by Annual Accounts until #153. The Tax capability does not import those CLI mechanics. The old Tax transport file is removed; the CLI uses the declared adapter and public polling contracts. The local rehearsal state machine now resides in this capability.

<!-- architecture-inventory
{"ports": ["CompanyTaxAuthority"]}
-->


`CompanyTaxRehearsalConfiguration`, `CompanyTaxRehearsalIO` and `rehearse_company_tax_return` expose the existing local prepare/resume workflow. The frozen configuration contains only nonsecret declarations. The capability owns approved test scope, no-activity admission, prior evidence identity, durable intent before credential checks, repair eligibility, instance/upload/validation transitions, human handoff, read-only receipt resume and completed replay. The local adapter owns paths, JSON decoding, atomic private evidence writes, clocks, revision lookup, schema execution and credential acquisition. Existing pure payload generation crosses the public Tax contracts in process. The final summary is immutable; internal checkpoint evidence remains private mutable workflow state. No genuine filing or provider operation is performed during local verification.

<!-- architecture-inventory
{"ports": ["CompanyTaxRehearsalIO"]}
-->


`CompanyTaxSourceQuery`, `CompanyTaxSourceSnapshot`, `CompanyTaxSourceEvidence`, `CompanyTaxHistoryCoverage`, `CompanyTaxSubmissionFact`, `CompanyTaxIncidentFact`, `CompanyTaxOutcomeFact`, `CompanyTaxCorrectionLink`, `CompanyTaxSourceFacts`, `CompanyTaxSourcePersistence`, `project_company_tax_source` and `verify_company_tax_source` publish immutable evidence of the recorded Tax source. The adapter reads all six owned families and positive migration evidence in one authorized owner repeatable snapshot. The SQL contract checks scope, retained submission identities, six-family reconciliation, source hashes, exact legacy writer fences, original mode constraints and the declared seven-table Tax extent. Missing proof cannot mean no submissions. A production-labelled or unknown-mode legacy row remains an unknown potential attempt and makes coverage incomplete because no Tax production journal exists in this stage.

Source readiness is currently blocked by the existing disabled Tax production implementation. A stored permission flag or TT02 receipt cannot enable it. This decisive gate does not certify any other readiness prerequisite or turn the caller-fact assessment into an authoritative source. Before production is enabled, the source version and readiness contract must include current durable Annual, Ledger and Investments facts. Test and simulation outcomes remain labelled with their original source/adapter modes, record identities, observation times and actor references. Local observation time is not authority event time; incident attribution stays unknown. Corrections require explicit recorded links. Billing alone applies commercial policy.

The deferred `20260914022608_company_tax_return_source_contract.sql` follows the four filing expansion contracts in the explicit runner. Its function remains unavailable before cutover and after full rollback. Source evidence verification rereads a fresh snapshot and rejects scope/version/digest drift, future evidence times or incomplete coverage. The evidence scope is Talli-recorded Company Tax, not all external authority filings.

`TaxDeliverySource`, `TaxDeliveryEnvelope`, `tax_delivery_digest`,
`prepare_tax_delivery` and `verify_tax_review` bind a complete, company/year-scoped
Annual/Ledger/Investments read to immutable statutory documents, the current
authority document reference and the schema pin. Preparation requires an explicit
no-additional-attachments answer and typed Tax-consumed annual facts; a caller-fact
assessment preview cannot establish that persisted source. Common Annual
readiness remains an independently published prerequisite for the application,
not a decision made by document preparation. Changed source, independently read
current schema or current authority document reference invalidate review.

`TaxMutationKind`, `TaxMutationIntent`, `TaxMutationRecord`,
`TaxMutationDisposition` and `plan_tax_mutation` define submit-once operation
policy. Persistence must atomically commit a unique new intent before execution.
An existing uncertain operation requires read-only reconciliation; expiry or a
changed request never permits another POST. Completed results have a closed,
operation-specific shape. These policy contracts do not yet constitute a
persisted delivery workflow, enable a provider or replace the disabled-production
source gate above.

The internal `CompanyTaxApplication` delivery-source read now composes the
existing exact-year Annual interview contract, every Ledger entry page, and
Investments' complete reporting snapshot in one verified repeatable transaction
with no business writes. Existing migration-fence row locks remain supported.
Owning adapters borrow only existing executor memberships, enforce
the verified subject/claims and isolation binding, and restore the Tax role on
success, SQL error or cancellation. The source keeps all upstream digests while
projecting selected-year facts into the characterized Tax calculator. Missing
interviews, malformed pages and unresolved source lineage fail closed. This
preparation seam has no public HTTP route, stored approval or authority effect.

Ledger's published amendment references identify administrative-cost reversals
for the distinct entry-based annual estimate. Statutory expenses and share losses
use net account balances, so full reversal/replacement chains do not double-count.
Unsettled investment-income and sale receivables (`1530`/`1570`) map to the pinned
2025 business code `1570` (other current receivables); settled balances cancel.
Current-asset occurrences reserve distinct paths for securities, bank and
receivables instead of colliding when the only investment is a current asset.

`TaxDeliverySchemaValidator`, `TaxSchemaValidation` and
`tax_delivery_schema_adapter` bind local validation to the exact immutable
documents and schema/code-list pin. The infrastructure adapter
`talli_backend.adapters.company_tax_schemas.PinnedTax2025Schemas` verifies the
packaged manifest and every resource against the fixed upstream commit, then
validates all three XML documents offline. It rejects DTDs/external resources,
unlisted business codes, substituted envelope bytes and inconsistent
company/year/party/current-reference bindings. The shipped Apache-licensed
resources retain their upstream license and provenance; runtime makes no fetch.

The release-only `scripts/check_company_tax_schema_drift.py` resolves the fixed
official branch once and checks all ten pinned delivery/current-response resources at that immutable commit.
The launch rehearsal requires this gate: drift blocks, incomplete reads remain
unavailable, and matching resources remain current when only other years change.
Comments and processing instructions cannot hide code-list text; validation
proofs continue to hash the exact original document bytes.

The single calculator has a versioned authority-code projection. Historical
characterization keeps its original Ledger-number labels. New delivery uses
`company-tax-delivery-2025-v1`: Ledger cost accounts `6420`,
`6700`/`6705`/`6720`, and `7770`/`7790`/`7795` map respectively to the official
2025 business codes `6400`, `6700`, and `7700`, aggregating each category while
retaining the contributing Ledger account references. Amount calculations and
bookkeeping accounts are shared; this adds no second writer. The old labels do
not constitute code-list validation or authorization for new delivery.

<!-- architecture-inventory
{"ports":["TaxDeliverySchemaValidator"]}
-->

<!-- architecture-inventory
{"ports": ["CompanyTaxSourcePersistence"]}
-->

`TaxDeliveryDraft`, `StoredTaxDeliveryDraft`, `TaxDeliveryDraftFact`,
`decode_tax_delivery_draft` and `TaxDeliveryDraftPersistence` retain exact
versioned draft bytes, source/review/schema proofs, company/year, actor,
command identity and server time. Duplicate keys, noncanonical JSON, lossy XML,
changed scope/proofs and unknown versions are rejected on read. Exact concurrent
replay returns the same original; a changed binding conflicts. Drafts grant no
Annual readiness, Billing entitlement, approval, dispatch or authority outcome.

The deferred `20261026062315_company_tax_delivery_journal.sql` adds the owned
append-only `delivery_drafts` store after the Tax predecessor is contracted.
Its full owned relation is `company_tax_filing.delivery_drafts`.
Restricted runtime roles receive only exact RPC access. Forced RLS permits the
accepted owner to read/insert; no update/delete policy exists. Writes require
READ COMMITTED and recheck owner/phase after the published company lock.
Rollback closes a volatile write fence checked after the company lock and revokes
the write RPC, including containment of calls already waiting. Originals and
source reads remain available. Reopening requires restoring the private fence
helper to true and the original exact EXECUTE grant.

Source V2 positively enumerates all eight declared Tax tables and every retained
draft, including per-draft digests/count, without altering V1's seven-table
extent. V1 correctly becomes incomplete. The adapter selects installed V2; if
it is missing, V1 cannot conceal an added store. Unknown extra stores, incomplete
enumeration and mismatched draft bindings prevent complete coverage. Read bounds
(1,000 drafts/64 MiB per scope) fail unavailable, never truncate. V2 observation
time is read after enumeration,
so a valid draft committed between transaction begin and its first repeatable
snapshot cannot be rejected as future evidence. Historical production-labelled rows remain unknown; prepared drafts stay out of submission
and outcome history. No hosted migration, provider call or public draft-write
route is enabled by these internal contracts.

<!-- architecture-inventory
{"ports":["TaxDeliveryDraftPersistence"],"ownedTables":["company_tax_filing.delivery_drafts"]}
-->

`TaxDeliveryDraftArchive` and `archive_tax_delivery_drafts` preserve every exact
canonical draft and its retained actor, scope, source/review/schema bindings and
server time. The original reader refuses invalid enumeration. Unknown effects
on a retained legacy submission do not erase otherwise positively covered draft
originals. The API `/api/v1/company-tax/archive-source/delivery-drafts-v1` returns
these originals only through the canonical fresh-MFA policy. A short READ
COMMITTED company guard encloses the separate repeatable source read and
rechecks current owner/MFA after it; no provider I/O occurs while it is held.

The draft table installs the existing Company Access archive-generation trigger.
Its exact enabled function/arguments are included in positive V2 coverage.
Temporary trigger EXECUTE authority and role memberships are restored after DDL.
New writes invalidate in-progress company exports; exact replay does not.
Containment preserves originals and generation tracking.

`PrepareTaxDeliveryDraft`, `TaxCurrentDocumentResponse`, `TaxCurrentDocument`,
`TaxCurrentDocumentKind` and `CompanyTaxCurrentDocumentReader` support server-owned
preparation. The fixed TT02 adapter exposes only a current-return GET through this
port, retaining exact original bytes and rejecting malformed UTF-8; legacy
transport text replacement remains characterized separately. The offline schema
adapter additionally pins the current-response XSD, checks the supported 2025
AS identity/year/reference, and refuses unrepresented tax fields, locked fields,
guidance and existing business documents. It cannot discard or change current
share facts while generating a complete new return.

The named `company-tax-delivery-preparation` workflow reads all owning source
contracts, closes SQL, rechecks current owner/MFA, then performs the authority
GET outside SQL. After rendering it holds the READ COMMITTED company guard
through a separate repeatable owner-source snapshot and draft persistence.
Drift conflicts. A concurrent committed command is replayed under the final
lock before comparing a regenerated observation timestamp. Authorized exact
command replay precedes external access and returns the committed original after
a lost response. Default application composition has no preparation reader; it
remains unavailable. No caller supplies Annual/Ledger/Investment facts, party,
current reference, XML, provider URL or credentials through the command.
The strict `POST /api/v1/company-tax/delivery-drafts` route accepts company,
2025 year and filing ID plus an idempotency header. Fresh canonical MFA is
required before the current-return GET and again after the final company lock.
Its response contains only immutable identifiers, hashes and server time; the
separate fresh-MFA archive read returns originals. Default HTTP composition is
unavailable until its preparation dependency is explicitly supplied.

Storage codec V2 adds the inspected current response and its exact raw bytes.
V1 keeps its original canonical field set and remains readable; it is never
silently upgraded to current-authority preparation. Source V2 binds each exact
canonical record digest and server time independently of Python class layout.
The deferred `20261026074827_company_tax_current_draft_v2.sql` verifies its exact
predecessor and shares one private store implementation behind version-specific
RPCs. V2 has its own volatile post-lock containment fence; its rollback retains
both codecs and preserves the V1 writer contract. The original global fence
continues to contain both. These drafts are neither paid entitlement nor filing
approval; provider mutation and default activation remain closed.

<!-- architecture-inventory
{"ports":["CompanyTaxCurrentDocumentReader"]}
-->

Reader-first rollout: deploy the compatible backend codec and web archive reader
before enabling V2 draft writes. Keep these readers as the minimum application
rollback target after any V2 record exists. Containment disables V2 writes but
retains both codecs; rolling back to a V1-only reader is unsupported.
The new V2 migration leaves its write fence closed. Only the owned loopback rehearsal
explicitly opens it; hosted activation requires a separate reviewed rollout.

`TaxDeliveryReviewApproval`, `approve_tax_delivery_review` and
`decode_tax_delivery_review_approval` bind the exact draft/review, complete
source, schema and current-original digests to the reviewing actor and an opaque
authority-context digest. A later observation time does not change identical
originals; changed bytes or interpreted authority identity invalidate review.
The initial `TaxDeliveryAuthorityMode` admits only a finite loopback rehearsal.
This commitment alone grants no runtime admission, common Annual readiness,
Billing entitlement or live filing authority. Current owner/MFA and guarded
source revalidation belong to the application before persistence.

The append-only delivery journal retains one review, and one intent/result pair
for each of create, upload, validation start and confirmation preparation.
`build_tax_delivery_mutation_request` and `complete_tax_delivery_mutation` build
the bound values; `decode_tax_delivery_mutation_request` and
`decode_tax_delivery_mutation_completion` recheck exact retained codecs.
`TaxDeliveryMutationRequest` rebuilds exact approved wire bytes without accepting
URLs or credentials. `TaxDeliveryMutationCompletion` binds normalized references
to the exact response original, including BOM and whitespace. Confirmation
preparation requires an instance read showing the confirmation task; a PUT
acknowledgment is insufficient. These records do not attest clean scanning,
successful validation, owner confirmation, submission or final receipt.
`TaxDeliveryCompletionOrigin` distinguishes mutation responses from instance
reads. `StoredTaxDeliveryEvent` binds each original to its recording actor/time;
`decode_tax_delivery_event` refuses unknown versions. `TaxDeliveryEventAppend`
reports the committed insertion/replay result. `TaxDeliveryJournalFact` is the
sanitized source-owned projection of the latest retained journal state.

`TaxDeliveryJournalPersistence` appends through one restricted RPC and reads a
complete journal in a repeatable snapshot. Company locking elects one insertion;
the caller must observe transaction commit before using `inserted=true`. A lost
commit acknowledgment leaves an uncertain intent: exact replay returns
`inserted=false` and only permits reconciliation. There is no lease or retry
reset. The same verified actor can append an exact request-bound result after
ownership or MFA changes during I/O. That narrow path cannot create an intent,
replace a result or read originals without current ownership and fresh MFA.

Deferred migration `20261026100000_company_tax_delivery_events.sql` leaves new
reviews/intents disabled. Its rollback also fences callers already waiting for
the company lock, retains originals and permits only bound late completions.
No runtime factory, HTTP writer or provider dispatcher enables this journal.
`TaxDeliveryJournal.plan` checks causal ordering, not runtime admission or
external prerequisites. Finite loopback admission, scan/validation observations,
dispatch/reconciliation workflows and connected approval remain unfinished.

Source V3 positively covers exactly nine owned tables, every event digest/count,
scope, recording actor, immutable draft and causal prefix, plus the enabled
archive-generation trigger. It reports reviewed/uncertain/mutation-completed
facts explicitly as finite rehearsal facts; they are never production attempts.
V1/V2 fail closed after the ninth table exists. Deploy V3-aware readers and finish
archive composition before any hosted migration; retain V3 readers on rollback.
The migration has isolated PG17 component coverage and a full local Supabase
topology proof with real signed login/TOTP tokens. The hosted topology has not
been expanded. Existing HTTP contracts retain their prior response shapes.

<!-- architecture-inventory
{"ports":["TaxDeliveryJournalPersistence"],"ownedTables":["company_tax_filing.delivery_events"]}
-->

`TaxDeliveryJournalArchive` and `archive_tax_delivery_journal` retain the complete
Source V3 draft/event originals and their source-owned facts. The application
holds the current READ COMMITTED company guard across the separate repeatable
source enumeration and checks current owner/MFA again before returning bytes.
The dedicated `companyTaxGetDeliveryJournalArchive` HTTP operation returns this
bundle only after that guard. An unresolved predecessor production effect keeps
its unknown attribution; it does not erase archive originals. Every other
coverage, extent, linkage, enumeration or archive-tracking failure blocks export.
The web export includes the exact returned journal bundle within its existing
company generation boundary. Real local Supabase login/TOTP tokens are verified
through Auth's current-user endpoint in the full topology tests; malformed or
AAL1 tokens and ownership revoked while waiting are denied. Previously committed
request-bound results remain retainable after revocation through the narrow
completion RPC, and cannot authorize a new request. Hosted activation remains
closed pending the guarded dispatch and finite admission workflow.

`ApproveTaxDeliveryDraft` binds the actor/company/year/filing, caller idempotency
key and exact displayed draft/review hashes. `AdvanceTaxDelivery` binds the retained
approval; changed retry keys never reset an existing mutation.
`TaxDeliveryProgress` publishes reviewed, uncertain or mutation-completed metadata
without originals or credentials. A mutation-completed create means only that
the instance was created, never submitted, owner-confirmed or receipted Tax.
`assert_tax_delivery_attempt_history` requires complete Source V3 coverage and
blocks another retained delivery from being bypassed with a new filing ID.
Correction/replacement admission remains closed until its terminal proofs exist.

`TaxDeliveryMutationAuthority` joins current-original reads and exact request
execution. Its only adapter is `LoopbackCompanyTaxDelivery`, confined to a
backend-issued finite local run. The application rechecks current owner/MFA,
source, schema and authority originals, commits the exact new intent, closes SQL,
then performs the fixed-path create. An uncertain intent never elects another
send. Results are bound to exact original bytes and retained through the narrow
original-actor completion RPC even if access changes during I/O. Approval retries
return the immutable original review receipt. Unknown create reconciliation has
no invented lookup or lease reset. Guarded upload requires Source V5; guarded validation requires Source V6 below.
Confirmation remains closed until its retained prerequisites are implemented.

<!-- architecture-inventory
{"ports":["TaxDeliveryMutationAuthority"]}
-->

The finite authority adapter bounds the complete HTTP operation, streamed body
and cleanup to five seconds, as well as individual network waits. Redirects and
retries are disabled; response bytes are bounded. Malformed/deep JSON becomes an
unknown retained operation outcome, including on the first HTTP response.

The deferred `20261026111629_company_tax_delivery_observations.sql` installs
Source V4 and a bounded journal V2 reader before opening any evidence writer.
The exact nine-table extent, existing FORCE RLS and original V1 codecs remain.
New writes default closed. The matching rollback contains new evidence writes
after company-lock waits while retaining all originals and compatible readers.
Deploy the compatible backend, client and export reader before enabling writes;
once a new codec is retained, an older reader must fail closed rather than erase
it from an export. Mutation containment remains independently controlled.
The generated archive client requests `readEvidence=true`. Without that explicit
negotiation, a V4 installation with predecessor-only records returns a fully
reprojected V3 archive. New records instead make a predecessor request unavailable;
they are never omitted. An older backend ignores the additive query and returns
its supported V3 archive, preserving both deployment orders before writer cutover.

`TaxDeliveryAdmissionEvidence` retains the exact nonsecret context named by the
review hash: finite scope, lifetime, request budget, loopback origin, credential
hash and restricted database identity hash. No credential or DSN is retained.
Review plus admission commit atomically; the review receipt stays immutable.
The successor contract is required for every new review or mutation intent.
Predecessor-only installations retain historical review/intent/result replay;
they cannot open a new dispatch without the admission store and reader.

`TaxDeliveryInstanceObservation` retains exact successful known-instance read
bytes, including BOM and whitespace. A known create result supplies the fixed
read target. Unknown create has no invented lookup. Explicit foreign scope is
rejected; missing, malformed or ambiguous metadata stays unknown and cannot
prove an empty instance. Positive metadata inspection includes scan and process
facts. Only the successor fresh empty-instance proof can authorize an upload;
metadata alone authorizes no validation, confirmation or final receipt.

Read evidence requires the successor contract. Current owner and fresh MFA are
checked before network and again before storing or disclosing a read. Network
runs outside SQL transactions. Unchanged read bytes reuse their first original
and recording time without advancing export generation; the later local read
time requires an explicit bounded upload prerequisite to become consequential. Evidence updates the last
event reference without inventing another completed mutation or submitted state.
Journal enumeration is bounded to 2,048 events/64 MiB per filing; source export
retains its 9,000-event/64 MiB company-year bounds. Exceeding a bound fails closed.
`TaxDeliveryReadOriginal` and `TaxDeliveryOriginalPurpose` define bounded exact
UTF-8 resource bytes, purpose, media type and successful read status.
`decode_tax_delivery_observation` rechecks closed codec fields, canonical bytes,
scope, original encoding and the expected digest before reconstructing evidence.

`TaxDeliveryEnvelopeObservation` and `decode_tax_delivery_envelope_observation`
retain exact known-instance file reads and bind their positive instance metadata
identity and data ID. Approved-byte equality requires exact hash, media and size;
`Clean` scan status remains a separate prerequisite. A changed BOM or whitespace
is retained as different bytes. Source V5 admits this codec to the journal;
its fixed-path read alone adds no upload or unknown-outcome clearance authority.

`TaxDeliveryReadReference` and `TaxDeliveryUploadPrerequisite` distinguish the
first retained instance original from its fresh backend observation time.
`bind_tax_delivery_upload_prerequisite` requires identical read content and a
positively empty, unarchived active data task within a 30-second observation
interval. The optional upload prerequisite selects mutation-request codec V2;
absent it, every V1 canonical byte remains unchanged. Source V5 / Journal V3
validate these references and fresh access/source guards before committing an
intent. Concurrent identical reads may reach storage in reverse order; the
first retained original remains immutable, and both observations must predate
the finished proof. A committed winner is replayed before comparing new proof
times. Only an acknowledged new committed intent elects one fixed-path POST.

`TaxDeliveryUploadReadEvidence` and `reconcile_tax_delivery_upload` build a V2
upload completion from exact bound metadata and file originals. Both canonical
originals are retained once inside the completion; exact request-body equality,
resource identity, scope, media and size are mandatory. This proves only upload
existence, including while a scan is pending or infected. It authorizes no
validation. Source V5 binds the completion to an already committed original-actor
upload intent. Known file results survive revocation during file GET; new reads
and drift evidence still require current owner/MFA. Unknown uploads never retry
POST and resolve only through exact known-instance metadata and file originals.
Concurrent recoverers preserve the first completed original. A different exact
completion cannot disclose it through the late-result RPC; a separate current
owner/MFA history read may replay the bound winner. Create advance/reconciliation
receipts stay scoped to create across later upload states.

The deferred `20261026124307_company_tax_guarded_upload_v2.sql` installs positive
Source V5 / Journal V3 readers over the same nine tables, with default-closed
guarded writers. Its rollback closes new guarded work after company-lock waits
and retains originals, readers and narrow known-result completion. New archive
clients request `readEvidence=true&readEvidenceVersion=2`. Predecessor requests
receive a complete reprojected V4 or V3 only while all retained codecs fit that
version; unsupported originals make the request unavailable, never incomplete.
No hosted/provider activation follows from installing the local successor.

`TaxValidationResponseInspection`, `TaxValidationResultCode` and
`TaxValidationCalculatedDocument` describe local structural inspection of the
separate pinned common V2 validation-response schema. Exact response and decoded
document bytes remain distinct. Counts expose calculation deviations, validation
deviations, guidance and failure reasons, including guidance accompanying
`validertOK`. No field is a filing-readiness attestation. The schema has no
company/year/job identity; known-job scope and calculated-document scope still
need separate checks before any consequential operation.

<!-- architecture-inventory
{"ports":["TaxValidationResponseValidator"]}
-->

`TaxDeliveryValidationPrerequisite` and
`bind_tax_delivery_validation_prerequisite` require fresh metadata and file
reads within one 30-second window, exact approved bytes, exact `Clean` scan
status, one reviewed data resource and an unarchived active data task. Fresh
read times remain separate from the first retained canonical originals. This
proof has no dispatch authority without the positive V6 intent/store and current
application access, owning-source, current-document and finite admission checks.
The release drift probe checks both the original delivery bundle and separate
validation-response bundle against one current official repository commit; a
changed, missing or unreadable response resource prevents a current verdict.

`TaxDeliveryValidationJobObservation` retains exact known-job status JSON;
`TaxValidationJobInspection` derives the documented `TaxValidationJobStatus`,
previous status and bounded timing fields. Malformed/ambiguous status remains
unknown; a recognizable foreign job is rejected. No lost job ID has a lookup
or retry path. `decode_tax_delivery_validation_job_observation` preserves exact
canonical originals and their stable content identities across later polls.

`TaxDeliveryValidationResultObservation` links exact XML to the same retained
start request and finished known-job original. The separate response schema pin
is rechecked during inspection; no caller-provided success flag is stored.
`decode_tax_delivery_validation_result_observation` retains unknown/malformed
XML originals without promoting them to a positive validation result. These
V5 journal/store refuses these new read codecs and V3 requests. Source V6 /
Journal V4 admit them only with complete prefix and positive contract proof.

The deferred `20261026143210_company_tax_validation_evidence_v1.sql` installs
Source V6 / Journal V4 over the same nine tables before opening its default-false
validation fence. The matching rollback closes new validation intents and read
writes after company-lock waits; every original and compatible reader remains.
Known original-actor start results retain their narrow completion path even
after access, MFA or containment changes. Raw status JSON uses exact lexical
integer fields; decimal/exponent timing stays unknown, while an unrelated large
numeric value cannot prevent retaining the original.

`CompanyTaxDeliverySubmission.advance_validation` requires a known upload,
complete current owning sources and current authority document, then fresh Clean
metadata plus exact approved file bytes. SQL commits the explicit V3 intent
before one fixed-path validation-start POST. Lost response/commit acknowledgment
never elects another start. Without a retained job ID, reconciliation performs
no lookup or provider operation. Known jobs alone can be polled; only a finished
status can supply a result GET target. Current owner/MFA gates run before each
network read and again before retaining or disclosing read originals. All I/O
runs outside SQL. Exact unknown/rejected XML stays retained without Tax success.

The archive client keeps `readEvidenceVersion=2` and additionally requests
`validationEvidence=true`. A prior backend ignores the additive capability and
returns its complete supported V5/V4/V3 archive. A V6 backend returns compatible
V5 to older clients only before validation originals exist; it never omits them.
Invalid higher-version proof fails before any downgrade. New web readers verify
scope, exact bytes, hashes, causal prefix, fresh Clean/file references and known
job/status/result identities; retaining XML does not itself prove local XSD or
inner-document scope, owner confirmation, submission or Tax acceptance.

Validation JSON inspection removes exactly one leading UTF-8 BOM while retaining
all original bytes; a second BOM remains unknown and cannot authorize a result.
The web reader rejects recognizable foreign job identity before checking timing
syntax and requires closed V3 request and new observation roots, scope wrappers
and time wrappers. No extra readiness field can extend a retained codec.

Finite envelope uploads follow the pinned authority API instructions: `Content-Type: text/xml` and `Content-Disposition: attachment; filename=skattemelding.xml`. The exact approved request body and stored request codecs remain unchanged. Both workflow and real HTTP/Postgres fixtures assert these fixed headers. Source: [official API V2 upload contract](https://github.com/Skatteetaten/skattemeldingen/blob/74d9c7dd020aa4701034194630c1b16609154986/docs/api-v2/README.md#last-opp-skattemeldingdata-skattemeldingxml-til-instansen).

`TaxCalculatedDocumentValidator` returns a derived `TaxCalculatedDocumentsInspection` for the exact retained response and draft. It requires the returned 2025 company Tax/business pair, validates their XSDs and existing pinned business-code categories, re-inspects the retained current-return party, and checks party/year on every scope-bearing document. Optional ordinary company computed-tax and display-summary documents use a separate integrity-checked bundle with exact packaged type-catalog imports. Personal, Svalbard, Petroleum, SDF and unhandled special regimes cannot be silently omitted. Computed tax carries no intrinsic party/year fields; the known-job chain must supply its context. Rejected result codes, deviations, guidance and exact decoded bytes remain visible; this inspection is not an owner review or submission permission. Both previous schema pins and original codecs remain unchanged.

<!-- architecture-inventory
{"ports":["TaxCalculatedDocumentValidator"]}
-->

`TaxDeliveryConfirmationPrerequisite` and `bind_tax_delivery_confirmation_prerequisite` bind fresh finished-job, exact validation-result and Clean approved-file reads to the separately pinned calculated-document inspection. `is_tax_delivery_owner_confirmation_instance` distinguishes ordinary `Task_2` from `Task_2Revisor` and feedback. `TaxDeliveryProcessAcknowledgment` and `decode_tax_delivery_process_acknowledgment` preserve a committed PUT acknowledgment without marking the operation complete. `TaxDeliveryConfirmationReadEvidence` and `reconcile_tax_delivery_confirmation` require complete scope-bound Task_2 metadata and the exact approved Clean file. These prepare owner review only; no owner-confirmation or actual submission command is implemented in this slice.

The deferred confirmation successor adds positive Source V7 / Journal V5 readers on the same nine tables before a private volatile default-false intent gate. The writer rechecks all new-work fences and current owner/MFA after the company lock, validates exact prior request/job/result/metadata/file references and bounded fresh times, and independently matches result code, all counts and decoded document bytes against retained XML. DTD/entity declarations are forbidden before SQL XML parsing; full XSD and intrinsic scope stay in the pinned adapter. Original-actor known acknowledgments/results survive revocation/containment using the committed request without broadening draft RLS. Runtime direct table access remains revoked. Rollback closes new confirmation intents while preserving originals, compatible readers and late-result retention.

The two explicit confirmation API routes accept scope/approval/key only. Default composition remains closed. Readers keep `readEvidenceVersion=2` plus additive `validationEvidence=true` and `confirmationEvidence=true`; older callers receive complete V6 only before confirmation originals exist. Web readers verify closed new codecs, raw hashes, known-job/result prefix, fresh original references and Task_1/Task_2 Clean/file proofs. They do not turn XML retention or a derived projection into browser XSD, owner-confirmation, submission or Tax-acceptance authority.
