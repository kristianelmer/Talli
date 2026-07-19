# Customer-ready browser rehearsal — 2026-07-15

Status: passed for the private-beta product boundary  
Application SHA: `28e4360b503ba3dbd8cb6e6b082803e447c68221`  
Target: `https://talli.no`  
Browser: Safari on macOS, existing authenticated beta account  
Operator: Codex, visually controlled through the local desktop session

This record contains no credentials, private document contents, or personal
identifiers. No record was deleted, no file was uploaded, no payment was created,
and no production submission was attempted during this rehearsal.

## Deployment proof

- `main` and `origin/main` resolved to the application SHA above after a
  fast-forward merge.
- The public home page returned HTTP 200 from Vercel.
- The deployed sign-up route exposed the new 12-character password requirement,
  proving that the promoted application revision had reached the public domain.
- The existing authenticated Safari session remained valid after a hard refresh.

## Desktop journey

| Area | Result | Evidence observed |
| --- | --- | --- |
| Session and workspace | Pass | Authenticated workspace loaded with one company and reported `Tilkobling OK`. |
| Customer input hygiene | Pass | Opening-balance, loan, purchase, sale, dividend, bank CSV, and manual-journal fields used empty inputs/placeholders instead of fabricated accounting values. |
| Dashboard | Pass | Counts and deadline states loaded; the next action routed to the dedicated filing journey. |
| Holding actions | Pass | Supported action catalogue loaded and recent persisted share purchases were visible. |
| Transactions | Pass | CSV import control, unmatched transactions, and reconciled activity loaded without error. |
| Year-end | Pass | Persisted positions/actions/costs forced `Ja` for shares owned, share activity, and costs paid; unrelated owner answers remained user-controlled. |
| Documents | Pass | Private upload/download controls loaded and the owner-only `Fjern feilopplasting` action was visible. It was intentionally not activated. |
| Filing overview | Pass | All three obligations loaded and truthfully reported remaining work. |
| Filing detail | Pass | Bank, billing, year lock, and year-end gates blocked progression; preview, authority confirmation, and archive remained unavailable. |
| Billing | Pass | The page stated that payment is not active and that the user will not be charged. No checkout or charging control was exposed. |

## Responsive journey

Safari was narrowed to a mobile-sized window. The billing page reflowed without
horizontal clipping, cards remained readable, and the desktop navigation collapsed
to an accessible `Meny` button. Expanding the menu exposed all customer routes and
the signed-in account controls. The window was restored after the check.

## Non-browser evidence carried by this release

- Full launch rehearsal: pass.
- TypeScript check: pass.
- Next.js production build: pass; all application routes built.
- Production dependency audit at high severity: zero vulnerabilities.
- Fresh local Supabase migration/RLS/storage rehearsal: pass with zero blocking
  advisor findings.
- Hosted deployed-schema contract: 20 required paths ready.
- Hosted Supabase advisors: zero error findings; leaked-password protection remains
  a paid-plan warning and is tracked as a launch decision rather than silently
  enabled.

## Remaining gates

This rehearsal authorizes the current invite-only/private-beta product posture. It
does **not** authorize production filing, live charging, or unrestricted paid
customer admission. Those capabilities remain fail-closed pending the named
authority, professional-review, security/recovery, payment, pilot, and final
founder signoffs in the customer-ready decision map.
