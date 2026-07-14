# Company Tax No-Attachment Boundary Design

Status: approved direction; implementation pending written-spec review

## Goal

Enforce the supported-case boundary for the company tax return before Talli
prepares an Altinn instance. Talli may prepare the return only when the owner
has explicitly confirmed that the filing needs no attachments beyond the
company tax return and its business specification.

This design is deliberately fail-closed. Talli does not infer the answer from
industry code, transactions, accounts, or previously accepted filings.

## Existing contract

The company-tax integration remains governed by:

- `docs/superpowers/specs/2026-07-14-company-tax-return-tt02-submission-design.md`
- `docs/filing/company-tax-return-authority-map.md`
- `docs/filing/authority-adapter-plans.md`
- the pinned Skatteetaten 2025 schemas and API documentation recorded by those
  documents

The supported payload continues to contain exactly the company tax return and
business specification. This design does not add an attachment API, an
attachment category, or an attachment upload path.

## Authoritative owner answer

Add an explicit annual-interview answer with this domain type:

```ts
type CompanyTaxAttachmentRequirement = "none" | "required" | "unknown";
```

The answer is stored as
`YearEndInterviewAnswers.company_tax_additional_attachments`.

The states mean:

- `none`: the owner explicitly confirms that no additional attachments are
  required. This is the only state that satisfies this boundary.
- `required`: the owner confirms that at least one additional attachment is
  required. Talli blocks company-tax preparation.
- `unknown`: the owner is unsure, the value is absent from historical data, or
  stored data cannot be parsed. Talli blocks company-tax preparation.

No missing, malformed, truthy, or legacy value may be coerced to `none`.

## Owner experience

Add the question to the control step of the year-end interview, because it
determines whether the case is supported rather than whether the owner has
submission authority:

> Krever skattemeldingen andre vedlegg enn skattemeldingen og
> næringsspesifikasjonen?

Present three explicit choices:

- `Nei, ingen ekstra vedlegg` -> `none`
- `Ja` -> `required`
- `Usikker` -> `unknown`

The help text explains that choosing `Ja` or `Usikker` prevents automatic
preparation and asks the owner to clarify the requirement with their
accountant or Skatteetaten. The summary step shows this as a blocking item, not
as an overridable warning.

The client sends the selected enum as a dedicated form field. It is not
encoded through checkbox presence and is not included in the boolean answer
key list.

## Persistence and parsing

Store the enum inside the existing `annual_data.answers` JSONB value. A SQL
schema migration or a new database column is not required.

Split the annual-data parsing contract:

- boolean interview fields continue through an explicit boolean-key list;
- `company_tax_additional_attachments` goes through a strict enum parser;
- a new form submission with a missing or invalid enum is rejected with a
  user-safe validation error;
- a historical or malformed stored row normalizes to `unknown` at the domain
  boundary so reads remain available while readiness fails closed.

Existing annual-data rows are not rewritten automatically. Their owners must
reopen and save the year-end interview with an explicit answer before company
tax preparation can become ready.

The answer does not participate in `noActivityConfirmed`. It is a supported-
case attestation, not evidence of company activity.

## Readiness behavior

`companyTaxReturnPayloadFeedback` becomes the single domain gate for this
boundary and emits stable blocking issue codes:

- `tax_return_attachment_requirement_unknown` when the answer is absent,
  malformed, or `unknown`;
- `tax_return_additional_attachments_required` when the answer is `required`.

An answer of `none` adds no attachment-boundary issue. All existing company-tax
issues still apply.

These issues flow through `annualReadiness` to the `skattemelding` obligation.
They do not block RF-1086 or annual-accounts preparation unless those
obligations have their own independent blockers. No warning override,
operator action, or authority status can waive either issue.

Payload rendering and the authority client keep their two-document interface.
They must not accept a caller-supplied attachment or bypass flag.

## Hash and audit binding

The complete `annual_data.answers` object is already included in the annual
basis used by the owner-dividend and annual corporate-document source hashes.
Persisting this enum in that object therefore binds the explicit answer into
the immutable review basis.

Changing the answer after review changes the annual-data hash and makes the
previously reviewed annual decision stale through the existing source-hash
checks. No parallel hash or special exception is introduced.

The existing year-end save audit event remains sufficient. It records the
change without copying raw annual answers or personal data into the audit
message.

## Failure behavior

- Missing and malformed values always behave as `unknown` for readiness.
- Invalid new form input is rejected; it never silently becomes `none`.
- `required` and `unknown` prevent company-tax preparation before network or
  Altinn mutation begins.
- A previously prepared artifact cannot be reused after the answer changes,
  because its bound annual-data hash is stale.
- Production authority capability remains disabled. This change neither
  grants production access nor changes any production endpoint guard.

## Verification

Implementation must add or extend tests that prove:

1. Annual-data parsing preserves each exact enum and never coerces missing or
   invalid input to `none`.
2. New form submissions require an exact enum value, while historical rows
   without it normalize to `unknown`.
3. `none` satisfies only this boundary; `required`, `unknown`, and a missing
   legacy value produce the expected stable blocking issue.
4. The blocker appears on the `skattemelding` readiness result without
   changing RF-1086 or annual-accounts readiness.
5. Changing the answer changes the annual-data source hash and invalidates a
   previously reviewed annual decision.
6. The owner interview renders all three choices and the blocking summary
   copy.
7. Company-tax payload and authority-client interfaces still accept only the
   two core documents.
8. Production-disabled capability tests and the complete launch rehearsal
   remain green.

Test fixtures that represent a supported company-tax case must set the answer
to `none` explicitly. Updating fixtures silently through a permissive default
is prohibited.

## Out of scope

- inferring attachment requirements from accounting data or industry codes;
- uploading, categorizing, validating, or transporting attachments;
- an operator, accountant, or administrator override;
- enabling a production client, endpoint, scope, or submission;
- changing Skatteetaten's personal final-confirmation requirement.

## Completion criteria

The implementation slice is complete when the enum is captured, persisted,
hash-bound, and enforced by company-tax readiness; legacy values fail closed;
the focused tests and full launch rehearsal pass; and production filing is
still disabled. Cases requiring an extra attachment remain unsupported until
a separately reviewed attachment design and TT02 evidence exist.
