# Copy & terminology guide

Talli speaks plain Norwegian to company owners. Owner-facing copy lives in
`app/lib/copy.ts` (`ownerCopy`) — never inline. This guide keeps the language
consistent and free of developer/infrastructure jargon.

Domain terms come from [`CONTEXT.md`](../../CONTEXT.md); reuse that vocabulary.

## Principles

1. **Norwegian first.** Every owner-visible string is Norwegian. Operator-only
   surfaces (the `(operator)` route group) and code/comments may stay English.
2. **No infrastructure jargon.** Owners never read implementation words. The
   compliance engine lives in `holding_core`; the UI describes outcomes, not
   plumbing.
3. **Calm and reassuring.** Short sentences, active voice, a confident-helper
   tone. State what happens next, not what failed underneath.
4. **One source of truth.** Add new owner copy to `ownerCopy`, then reference it.

## Banned in owner-facing text

These never appear in anything an owner can read (labels, headings, helper
text, error messages):

| Don't write | Write instead |
| --- | --- |
| Supabase, database, DB | Tilkobling / (omit) |
| RLS, tenant-isolasjon | "Hvert selskaps data er adskilt" |
| audit trail, audit event | logg, loggen |
| MFA, step-up | ny identitetsbekreftelse |
| notification outbox | "vi sender varselet" |
| ledger | regnskap, regnskapet |
| billing, billing-admin | fakturering |
| filing (as a noun) | innsending |
| filing package | innsendingspakke |
| workspace | arbeidsflate |
| readiness | status |
| gate / gated | (describe the outcome) |
| launch boundary | (describe the limit plainly) |

## Domain vocabulary (owner-facing Norwegian)

| Concept (CONTEXT.md) | Owner-facing Norwegian |
| --- | --- |
| Annual holding compliance loop | Årsoppgjør |
| Shareholder register statement | Aksjonærregisteroppgaven |
| Company tax return | Skattemelding for AS |
| Annual accounts | Årsregnskap |
| Holding action | Holdinghandling |
| Simple holding AS | Holdingselskap (enkelt AS) |
| Out-of-scope pattern | Trenger regnskapsfører / utenfor støttet løype |
| Mid-year onboarding | Oppstart fra valgt regnskapsår |

## Tone examples

- Empty state: "Sett opp holdingselskapet ditt — det tar under ett minutt."
- Blocked obligation: list the plain-Norwegian `hard_blocks` as "Dette gjenstår:".
- Sensitive action: "Krever ny identitetsbekreftelse."
- Service down: "Innlogging er midlertidig utilgjengelig. Prøv igjen om litt."
