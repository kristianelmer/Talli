# RF AR feedback parser — observed service receipt

The 2026-09-15 approved synthetic no-activity submission returned XML with
namespace `urn:ske:fastsetting:innsamling:aksjonaeroppgave:ar_til_mag:v0_1`.
[`acceptance-receipt-20260915.json`](acceptance-receipt-20260915.json) binds its
original bytes to the submitted company/year and independently reviewed
Dialogporten Submission → Acceptance → attachment chain. The accompanying
PDF agrees with its `godkjent` status and provider reference `AKRE22100`.

The classifier recognizes the single delivery's direct
`leveranse/leveranseoppsummering/leveransestatus`, requires its company and
income year to match expected context, and requires a separately verified
related-transmission ID matching the expected HTTP submission ID. The internal
`magnetArInfo/innsendingsId` is not that HTTP ID; it is never returned as one.
Missing context, malformed XML, duplicate decision/identity values, unexpected
namespace, unknown status or ambiguous delivery structure fail closed. Both
related transmission IDs must be UUID strings. XML nesting is now bounded to
64 elements for all supported feedback profiles, including legacy v2; deeper
extensions that were previously tolerated are intentionally rejected.

This is a parser for the observed service format, not a claim of full XSD
conformance. The pinned Skatteetaten API documentation tree
`05ab5028d899878094d8f349db8b46081c3f4eb9` contains the submitted RF main/under
schemas and generic v2 feedback schemas; it does not contain an AR-to-MAG
feedback XSD. Public exact-namespace searches on 2026-09-15 returned no result.
Current official receipt-schema publication and drift coverage remain pending.

The existing archive-only reconciliation does not supply the new identity
context and therefore cannot accept this format yet. Canonical Dialogporten
receipt discovery must establish the company/service-bound dialog, original
Submission and related response transmission, retrieve exact Attachment IDs
through the official RF document endpoint, retain all receipt bytes and pass
that verified relationship to the classifier. PDF presence alone cannot
classify a decision; complete companion XML and conflict checks are required.
