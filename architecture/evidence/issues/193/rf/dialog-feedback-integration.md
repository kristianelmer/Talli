# Canonical RF Dialogporten feedback integration

The original submission confirmation supplies the Dialogporten dialog ID and
submission transmission ID. Recovery reads the latest succeeded confirmation
under the active feedback lease and checks its submission ID against the stored
feedback reference. The company comes from the verified owner session.

The backend binds two tokens with the same delegated company and external
reference: the RF scope for documents and `digdir:dialogporten` for discovery.
Both tokens are acquired before a new filing begins and discarded on success,
failure or cancellation. This code does not activate any provider client scope.

Discovery reads only the fixed test/production Dialogporten end-user dialog
endpoint. It verifies dialog, company, RF service and original Submission;
related transmission and attachment IDs must be valid and unique. Known
transmission categories are retained. Only Acceptance, Rejection and Decision
can accompany a terminal XML decision; a contradictory category/status or
a different category requires action. This is conservative conflict handling
pending broader service-case conformance, not a claim of an official XML/type
mapping beyond the observed Acceptance/godkjent receipt. Missing
access or incomplete exclusions fail closed. A bounded 2 MiB JSON read rejects
duplicate keys and non-finite values. Presentation URLs, tokens, actors and
free text never become application data. Returned values retain only IDs,
provider creation time and exact attachment extent. All directly related
transmissions are included for later decision/conflict checks.

The RF endpoint is constructed from transmission and Attachment IDs as specified
in [RF OpenAPI 1.2.0](https://api.swaggerhub.com/apis/skatteetaten/innrapportering-aksjonaerregister-api/1.2.0).
The [Dialogporten end-user OpenAPI](https://platform.tt02.altinn.no/dialogporten/swagger/v1.enduser/swagger.json)
is pinned by the earlier receipt action to SHA256
`c9d07cf4d258d99ab96bc9149980a9718171ff7e0fa1c9f61a5621808cd42830`;
RF OpenAPI bytes are pinned to
`1dc44e55fd993872e1cfd30fdbe59bd2f612e8e34de6d3e4c5dfdf34ab022947`.

Acquisition reads the complete related receipt set within the existing 60-second
and 32 MiB scan bounds before any artifact write. Each XML decision receives the
verified submission relation plus expected company/year. The companion PDF is
retained under that XML decision; PDF alone cannot finalize. Unknown formats,
missing XML, inconsistent decisions or missing attachments do not accept.
Original receipt bytes and hashes are unchanged. Artifact authority-reference
metadata records dialog, submission, response and attachment IDs, expected
company/year and provider creation time separately from journal observation time.
A deterministic Talli-owned XML provenance manifest independently retains every
attachment relationship and content hash, even when identical provider bytes
share one stored Document. Its reference explicitly identifies it as Talli
provenance, not a provider receipt. Only after all artifact writes, including
this manifest, succeed may the owner append a final decision.

The local old archive-only entry remains available for characterized legacy
callers. Both production workflow paths explicitly supply discovery and the
stored dialog context. No filing mutation method is exposed by either read port.

Limits: no new provider call or production enablement is covered by these local
changes. The discovery bounds are operational safeguards, not a narrowed company
scope. Canonical live conformance, receipt XSD publication/drift coverage,
correction cases, representative company/load coverage and full RF gates remain
pending. Formats beyond the current RF/Document storage allowlist remain blocked.
