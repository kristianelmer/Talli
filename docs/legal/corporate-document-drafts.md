# Corporate document drafts for simple owner dividends

Status: implemented draft generator; legal review and staging storage rehearsal pending
Last updated: 2026-07-13

Talli generates two unsigned PDF drafts when a supported owner dividend is
posted:

- board proposal and board-protocol draft;
- general-meeting protocol draft.

The files are working papers, not automatically valid resolutions. Every page
labels the artifact as an unsigned draft. The owner must verify the company
facts, meeting details, authority, financial assessment, attendance, voting,
and signatures before use.

## Supported boundary

The automated flow is limited to an ordinary cash dividend where:

- all shareholders come from the locked opening shareholder register for the
  selected company-year;
- every registered share receives the same amount;
- the total can be divided into whole øre per share;
- the total does not exceed the entered distributable equity;
- entered post-payment liquidity is not negative;
- payment is not dated before the general-meeting decision.

Unequal dividends, non-cash distributions, missing shareholders, fractional
øre allocation, and unsupported ownership/tax cases must be stopped or handled
outside this simple workflow.

## Persistence boundary

PDF bytes are generated and validated before upload. Both objects must exist in
the private `company-documents` bucket under the company/year path before one
database transaction inserts the ledger entry, holding action, and both
document records. A failed upload or transaction removes still-unreferenced
objects. Persisted drafts use status `generated_unsigned`; storage does not imply
signature or approval.

## Source basis

The draft content and review prompts were checked against current Altinn
guidance on 2026-07-13:

- [Generalforsamling](https://info.altinn.no/starte-og-drive/drive-bedrift/drift-og-administrasjon/generalforsamling/): the board proposes dividend, the general meeting decides, and a protocol is required.
- [Praktisk styrearbeid](https://info.altinn.no/starte-og-drive/drive-bedrift/drift-og-administrasjon/praktisk-styrearbeid/): board protocols should record meeting facts, treatment, proposals, and decisions, and the board must assess adequate equity and liquidity.
- [Aksjeeier](https://info.altinn.no/starte-og-drive/drive-bedrift/drift-og-administrasjon/aksjeeier): a general-meeting dividend cannot exceed what the board proposed or accepted.
- [Altinn document templates](https://info.altinn.no/starte-og-drive/dokumentmaler/last-ned-dokumentmaler/): official template collection for human comparison during legal review.

These sources guide the draft fields; they are not a substitute for legal,
accounting, or tax review. A named reviewer must approve the template wording
before public launch.
