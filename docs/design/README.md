# Talli design language — "Calm Nordic"

> Status: **Approved** by Kristian Elmer (founder), 2026-06-24.
> Direction chosen: **Calm Nordic** — keep the green, drop gradients for flat
> refined colour, Inter typeface, generous whitespace, soft shadows. Modern,
> understated, trustworthy Nordic-fintech feel.
>
> This is the design spec for issue #91. The component library (#92) implements
> it from [`tokens.css`](./tokens.css) — the canonical token source. Components
> must reference the named tokens, never raw hex/px values.

## 1. Principles

1. **Calm over loud.** This is an app an owner visits a few times a year to stay
   compliant — not a marketing page. In-app type tops out at `--font-display`
   (32px), not the 84px hero. Emphasis caps at weight 700.
2. **Plain Norwegian, no infra.** The UI never surfaces Supabase / RLS / DB /
   "launch boundary" / signoff-key jargon to owners. Operator tooling lives
   behind the operator route group.
3. **One decision at a time.** Wizards and forms ask for one thing per step and
   always say what happens next and why.
4. **Status is never colour alone.** Every status pairs a colour with a label
   (and usually an icon) so it is legible to colour-blind users.
5. **Trust through restraint.** Flat colour, hairline borders, soft diffuse
   shadows. No gradients. Gold is a sparing accent, never a primary action.

## 2. Typeface

- **Inter** for all UI and headings. Full Norwegian glyph coverage (æ ø å).
- **Self-host via `next/font/local` or `next/font/google` with
  `display: "swap"`.** Inter must be bundled/self-hosted — do **not** hot-link a
  third-party font CDN at runtime. This keeps user IPs off a US font CDN and is
  consistent with the EEA data-location / SCC posture recorded in the legal pack
  (`docs/legal/`).
- Monospace (`--font-mono`) for org numbers, money in dense tables, and raw
  receipt/XML/JSON blocks.
- Enable `font-variant-numeric: tabular-nums` for all amounts and tables so
  figures align.

### Type scale (tokens)

| Token            | Size | Use                                   | Line-height        |
| ---------------- | ---- | ------------------------------------- | ------------------ |
| `--font-display` | 32px | In-app page hero / screen title       | `--leading-tight`  |
| `--text-2xl`     | 28px | Section titles                        | `--leading-snug`   |
| `--text-xl`      | 22px | Card titles, large numbers            | `--leading-snug`   |
| `--text-lg`      | 18px | Lede / intro paragraph                | `--leading-normal` |
| `--text-md`      | 16px | Body default                          | `--leading-normal` |
| `--text-sm`      | 14px | Labels, secondary text                | `--leading-normal` |
| `--text-xs`      | 13px | Eyebrows, badges, captions, table heads | `--leading-snug` |

Weights: 400 body, 500 medium, 600 semibold (most emphasis), 700 bold (headings
/ key numbers). **800 is reserved for the marketing site only.**

## 3. Colour

Built on the existing earthy-green palette, formalised and flattened. Full token
list in [`tokens.css`](./tokens.css). Highlights:

- **Canvas** `--color-bg` `#f6f3ee`, **surfaces** white, **sunken** `#f7f5f0`.
- **Primary ink** `--color-text` `#16201b`; secondary `--color-text-muted`.
- **Brand green** `--color-brand` `#0d6b57` (actions, links, active), hover
  `--color-brand-strong`, tint `--color-brand-soft`.
- **Gold** `--color-gold` — sparing accent only (e.g. a "founder price" mark),
  never a button or primary surface.

### Semantic status (paired base / soft / text)

| Role                | Base token        | Soft bg                | Text token             |
| ------------------- | ----------------- | ---------------------- | ---------------------- |
| Success / ready     | `--color-success` | `--color-success-soft` | `--color-success-text` |
| Warning / review    | `--color-warning` | `--color-warning-soft` | `--color-warning-text` |
| Blocked / error     | `--color-danger`  | `--color-danger-soft`  | `--color-danger-text`  |
| Draft / neutral     | `--color-draft`   | `--color-draft-soft`   | `--color-draft-text`   |
| Info / accountant   | `--color-info`    | `--color-info-soft`    | `--color-info-text`    |

### Domain status → token map (use everywhere a filing/task status renders)

| Domain status (no)        | English          | Tokens   |
| ------------------------- | ---------------- | -------- |
| Utkast                    | Draft            | draft    |
| Trenger gjennomgang       | Needs review     | warning  |
| Blokkert                  | Blocked          | danger   |
| Klar til innsending       | Ready to file    | success  |
| Levert                    | Filed / submitted| success (use `--color-brand` for the icon to read as "done & official") |
| Til regnskapsfører        | Needs accountant | info     |

Contrast: body ink on canvas, white on brand, and each status `*-text` on its
`*-soft` background all meet WCAG AA. `--color-text-muted` is for ≥14px only.

## 4. Spacing, radii, elevation

- **Spacing**: 4px base scale `--space-1..9`. App screens use `--space-5`/`-6`
  between sections (not the marketing `--space-9`). Content max-width
  `--content-max` (1100px); single-column forms `--reading-max` (560px).
- **Radii**: `--radius-sm` inputs/badges/small buttons, `--radius-md` cards,
  `--radius-lg` modals, `--radius-pill` badges/meters.
- **Elevation**: `--shadow-sm` resting cards, `--shadow-md` raised/hover,
  `--shadow-lg` the headline status panel, `--shadow-focus` the focus ring.
  Focus is **always** visible on keyboard navigation.

## 5. Component guidance

### Buttons
- Variants: **primary** (solid `--color-brand`, white text), **secondary**
  (surface + `--color-border`, ink text), **ghost** (text-only, brand on hover),
  **destructive** (solid `--color-danger`). Weight 600, `--radius-sm`,
  min-height `--control-height`, no gradients. Focus = `--shadow-focus`.
- One primary action per view. Destructive actions confirm before running.

### Forms
- Label **above** the field (`--text-sm`, weight 500/600, `--color-text-muted`).
- Inputs: white, 1px `--color-border`, `--radius-sm`, min-height
  `--control-height`. Focus = brand border + `--shadow-focus`.
- Helper text `--text-xs` muted below the field. Error state: `--color-danger`
  border, `--color-danger-text` message with an icon, never colour-only.
- Single column, `--reading-max`. Group related fields; avoid dense grids on
  owner-facing forms.

### Wizards / steppers (onboarding, holding actions, year-end)
- Horizontal numbered stepper on desktop, vertical on mobile. States: **done**
  (check, `--color-brand`, `--color-brand-soft` fill), **current** (brand ring),
  **upcoming** (muted). Show "Steg 2 av 5".
- One decision per step. Persistent **Tilbake** / **Lagre og fortsett**. Save
  progress between steps. Branching is allowed — skip steps that don't apply and
  explain why a step appears.
- Each step states what it's for and what happens after in plain Norwegian.

### Empty states
- Calm, not alarming: a simple mark/illustration placeholder, a one-line
  plain-Norwegian explanation, and a **single** primary action (e.g. "Legg til
  første transaksjon"). Never show raw infra, stack traces, or empty tables with
  jargon headers.

### Status badges
- Pill (`--radius-pill`), `--text-xs`, weight 600, `*-soft` background +
  `*-text` colour from the matching semantic pair. Always include the label
  text; add a small icon for ready/blocked. Use the domain status map above.

### Tables & numbers
- `tabular-nums`, right-align money, `--text-xs` uppercase muted column heads,
  hairline row borders. Keep owner tables short; push detail to a drawer/expand.

## 6. Annotated screen references

Not pixel mockups — token-level direction for the journey issues (#94–#101):

- **Owner dashboard (#94).** Canvas bg; a single "next best action" card
  (`--shadow-md`, `--radius-md`) at the top with one primary button; below it a
  calm row of status cards (this year's filings as badges). No meters/jargon.
- **Onboarding wizard (#95).** Centered `--reading-max` column, horizontal
  stepper, one question per step, brand primary "Fortsett". Warm, reassuring
  copy.
- **Holding-action wizard (#96).** Same stepper pattern; branches by action type
  (utbytte, kapitalforhøyelse, …). Confirmation step summarises what will be
  booked before committing.
- **Filing flow (#98).** Three calm stages — *Klargjør* (readiness checklist as
  badges), *Forhåndsvis* (preview, mono receipt block on `--color-surface-sunken`),
  *Bekreft* (single confirm with a clear "this is a preview / not yet live"
  notice while in simulation).
- **Empty archive (#100).** Empty state pattern: mark + one line + "Last opp
  første dokument".

## 7. Decision record

- **Direction**: Calm Nordic (founder-approved 2026-06-24). Keep green brand,
  remove gradients, demote gold to a sparing accent.
- **Typeface**: Inter, self-hosted (no third-party font CDN at runtime) for the
  EEA data-location posture; tabular numerals for money.
- **In-app vs marketing**: in-app display caps at 32px / weight 700; the 84px /
  weight 800 marketing scale stays only on public landing pages.
- **Source of truth**: [`tokens.css`](./tokens.css). #92 implements components
  against these tokens with no further design input required.
