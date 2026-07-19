# Annual-reporting workspace design

## Status

Approved design brief. Ready for implementation planning after user review of this written artifact.

## Feature summary

The annual-reporting workspace is the production-ready authenticated surface where an owner completes the full annual reporting cycle for one simple Norwegian holding AS and one reporting year. It replaces the current long prototype page with a focused product shell covering Aksjonærregisteroppgaven, Årsregnskap, Skattemelding, shared readiness, review, documents, and submission.

Every visible state and action uses the existing backend as its source of truth. The workspace must not introduce demo data, fabricated completion states, or UI-only filing logic.

Everyday holding actions remain separate destinations reached through the main product navigation. Invited reviewers use the same annual workspace with role-aware controls rather than a separate reviewer product.

## Primary user outcome

On entering the workspace, the owner must immediately understand:

1. What is already complete?
2. What blocks filing?
3. What should I do next?

Talli recommends one next action while allowing the owner to open any available obligation or supporting area. Dependencies may restrict an action, but they must not hide relevant records or leave disabled controls unexplained.

## Design direction

### Selected approach

The selected visual probe is **A: obligation-led workspace**. The overview leads with one recommended next action, followed by three scannable filing-obligation rows and a narrow contextual rail for deadlines, documents, and reviewer activity.

The final direction incorporates two useful ideas from the rejected probes:

- Explicit dependency and milestone states from the milestone-led probe.
- Contextual blocking explanations from the filing-workbench probe.

The milestone-led probe was not selected because it overstates sequence in a workflow that must remain non-linear. The filing-workbench probe was not selected because its density and tab-first topology feel closer to accountant-practice software than an owner-managed product.

### Visual system

- **Color strategy:** Restrained. Filing Green remains below roughly ten percent of a normal screen.
- **Theme scene:** A holding-company owner works on a laptop in a bright home office, focused and mildly anxious about getting annual reporting right. The scene requires a light, highly legible interface.
- **Creative north star:** The Clear Desk.
- **Character:** Quiet confidence expressed through Nordic clarity, flat-by-default elevation, and precise, familiar controls.
- **Anchor references:** GOV.UK task-list clarity, Stripe's precise handling of status and exceptions, and Linear's restrained navigation. These are behavioral references, not branding to imitate.

The workspace follows `PRODUCT.md` and `DESIGN.md`. It explicitly rejects visual imitation of Fiken, generic AI-product styling, cream or beige canvases, decorative gradients, glassmorphism, hero metrics, repeated card grids, uppercase eyebrows, wide ghost shadows, and excessive rounding.

## Scope

- **Fidelity:** Production-ready.
- **Breadth:** The complete annual-reporting surface, not only the overview.
- **Interactivity:** Shipped-quality responsive workflows connected to existing server actions and persisted data.
- **Roles:** Owner and invited reviewer use the same surface. Permissions alter available controls without changing the underlying information architecture.
- **Accessibility:** WCAG 2.2 AA, including keyboard operation, visible focus, screen-reader semantics, sufficient contrast, non-color status cues, and reduced-motion support.
- **Time intent:** Polish until ready to ship.

The design includes the annual overview, three obligation workspaces, shared readiness and review, documents in filing context, and submission states. It excludes redesigning the everyday holding-action workflows themselves.

## Information architecture

### Product shell

The compact persistent navigation contains:

- Årsrapportering
- Handlinger
- Transaksjoner
- Dokumenter
- Selskap
- Innstillinger

The active company and reporting year remain visible in the workspace header. Desktop uses a compact labeled navigation area. Narrow screens collapse the same structure into a labeled menu; an unlabeled icon rail is prohibited.

### Annual overview

The overview is an obligation-led control surface, not a generic dashboard. Its information order is:

1. A restrained annual-status header identifying company and year.
2. One prominent `Neste steg` action with a short reason.
3. Three obligation rows: Aksjonærregisteroppgaven, Årsregnskap, and Skattemelding.
4. A short explanation that the recommended order is optional where dependencies allow.
5. Contextual deadlines, relevant documents, and reviewer activity in a narrow secondary rail.

Each obligation row contains its name, owner-level explanation, explicit status, deadline, progress, dependency explanation, and action. Rows use dividers and spacing rather than repeated cards.

The contextual rail becomes contextual drawers or inline sections on narrow screens. It must never reduce the primary obligation list below a readable width.

### Obligation workspaces

All three obligations share one structural template so the owner does not relearn the product:

1. Purpose and filing deadline.
2. Readiness checklist.
3. Missing information and blocking explanations.
4. Supporting documents and evidence.
5. Reviewer comments attached to relevant requirements.
6. Review and submission action.

The shared template defines hierarchy and interaction behavior; each obligation supplies its own data, validation, evidence, and authority-specific requirements.

### Review and submission

The final review surface summarizes all obligations, accepted warnings, unresolved blocks, authority permissions, payment gates, and submission readiness. Submission remains unavailable until backend gates permit it. MFA or step-up appears only when the backend requires it.

The final confirmation identifies the company, reporting year, obligation, authority path, and consequences of submission. A successful submission exposes the durable receipt and archive location.

## Interaction model

- Opening the workspace lands on the annual overview.
- `Neste steg` deep-links to the exact incomplete requirement, not merely the obligation homepage.
- Obligation rows remain independently navigable where dependencies permit.
- Unavailable actions remain inspectable and explain exactly what unlocks them.
- Validation changes only after persisted backend changes; unsaved work never appears complete.
- Reviewer comments attach to obligations or readiness requirements rather than a detached general inbox.
- Owner-only actions remain visible to reviewers as read-only context where appropriate.
- The interface uses inline and progressive workflows before considering a modal.
- Short confirmations may use a dialog only when interruption is necessary and the decision is reversible or clearly explained.
- State transitions use 150–250ms exponential ease-out feedback and respect reduced-motion preferences.

## Roles and permissions

### Owner

The owner can complete supported data requirements, resolve warnings, request review, confirm authority, pass step-up, and submit when backend gates allow.

### Reviewer

The reviewer uses the same navigation and obligation views. They can inspect filing inputs and evidence, add or acknowledge comments where permitted, and see owner-only actions as read-only context. Reviewer permissions must never be inferred from presentation; every mutation remains server-authorized.

### Restricted or expired access

When a role lacks permission or an invitation is expired or revoked, the interface keeps authorized context visible, disables mutation, and states why. It does not silently remove an action the user reasonably expects to find.

## Data flow and module boundaries

The workspace consumes the existing company, reporting-year, filing, readiness, document, reviewer, authority, billing, MFA, and submission data. Server state remains canonical.

The implementation should separate the current monolithic page into bounded units with clear inputs:

- **Annual workspace shell:** company/year context, primary navigation, role context, and responsive framing.
- **Annual overview:** derives the next recommended action and renders the three obligation summaries.
- **Obligation workspace:** shared layout contract for purpose, readiness, evidence, comments, and action.
- **Readiness presentation:** translates backend validation and gate results into owner-level status, explanation, and resolution links.
- **Reviewer context:** comments, acknowledgements, and permission-aware controls.
- **Submission review:** authority, billing, step-up, confirmation, pending, receipt, and failure states.

These units consume typed view models derived from existing backend records. Presentation components must not duplicate accounting rules or decide readiness independently.

After a successful mutation, the affected server data is revalidated and the UI renders the persisted result. Optimistic completion is prohibited for filing, authority, billing, review acknowledgement, and submission transitions.

## Key states

### First year or empty

Explain the annual loop and lead directly to the first required setup action. Do not show an empty dashboard or a collection of disabled cards.

### Loading

Use skeletons that preserve the final layout. Do not use a page-center spinner.

### In progress

Show completed work, remaining requirements, dependencies, and the next recommended action.

### Ready

State exactly what is ready and which action is now available. Readiness must include text and iconography, not color alone.

### Warning

Explain the concern, consequence, and whether explicit acceptance is permitted. Accepted warnings remain visible in final review.

### Blocked

Identify the blocking requirement and link directly to its resolution. A disabled action without an explanation is a defect.

### Unsupported case

Stop only the affected filing, explain the support boundary in plain language, direct the owner to accountant assistance, and preserve access to unaffected records.

### Reviewer activity

Show each comment at the relevant obligation or readiness requirement with author, role, timestamp, acknowledgement state, and permitted response.

### Permission restricted

Keep authorized content visible while disabling mutation with a plain-language explanation.

### Backend failure

Preserve entered data where possible, explain what failed, state whether anything was saved, and offer an appropriate retry without implying completion.

### Submission pending

Prevent duplicate submission, show durable progress, and keep the user on a recoverable state if they return later.

### Submission success

Show the receipt, timestamp, filing identity, archive location, and next obligation or completion state.

### Submission failure

Preserve the attempt record, distinguish retryable from terminal failures, and provide the correct recovery or escalation path.

### Overdue

Elevate the deadline and required action without turning the whole interface red. Preserve the same navigation and resolution model.

## Content requirements

All customer-facing copy is Norwegian-first and plain-spoken. Necessary accounting and authority terminology is introduced with owner-level explanation.

The surface requires:

- Obligation names and concise owner-level explanations.
- Official deadlines and reporting year.
- Explicit statuses: not started, in progress, ready, warning, blocked, submitted.
- Next-action labels beginning with a clear verb.
- Dependency, validation, and unsupported-case explanations.
- Reviewer identity, role, comment context, acknowledgement, and timestamp.
- Document type, period, source, upload state, and relationship to a filing.
- Submission authority, confirmation text, receipt, and archive location.
- Error messages that state what happened, what was preserved, and what to do next.

Launch scope has exactly three obligations. Supporting tasks, documents, and comments are dynamic. Long collections use progressive disclosure or pagination instead of expanding the overview indefinitely.

## Responsive behavior

- Desktop keeps the compact navigation, main obligation surface, and contextual rail visible when space permits.
- Tablet collapses the contextual rail before compressing the main obligation content.
- Mobile uses a labeled navigation menu, stacks obligation-row metadata in reading order, and moves contextual documents or reviewer activity into inline sections or drawers.
- Primary and secondary actions remain distinguishable when full-width.
- Tables or evidence with many columns use a deliberate responsive representation; horizontal overflow is permitted only when the data genuinely requires a table.
- Long Norwegian labels and dynamic organization names must wrap without obscuring status or actions.

## Error handling and recovery

Every error state must answer three questions:

1. What happened?
2. Was my work saved?
3. What can I do next?

Retryable failures retain a visible retry action. Terminal or unsupported outcomes expose escalation. Submission failures never discard the attempt or receipt evidence. Permission and step-up errors return the user to the exact blocked action after successful reauthentication when backend behavior permits it.

## Accessibility

- Meet WCAG 2.2 AA contrast and interaction requirements.
- Support full keyboard navigation in logical reading order.
- Use visible focus styles from `DESIGN.md`.
- Announce validation summaries, status changes, submission progress, and errors to assistive technology.
- Pair every semantic color with text and, where useful, an icon.
- Use native controls and landmarks before custom interaction patterns.
- Keep touch targets at least 44px high for primary controls.
- Respect reduced motion and preserve content visibility when motion is disabled.

## Verification strategy

Implementation verification must cover:

- Owner and reviewer permission variants.
- The three obligation summaries and their detail workspaces.
- First-year, loading, in-progress, ready, warning, blocked, unsupported, overdue, and backend-error states.
- Submission pending, success, retryable failure, and terminal failure.
- Direct linking from `Neste steg` to the exact unresolved requirement.
- Persistence-backed status refresh after mutations.
- Prevention of duplicate submissions.
- Keyboard-only completion of all supported workflows.
- Screen-reader labels and live announcements for validation and submission.
- Desktop, tablet, and narrow mobile layouts with long Norwegian content.
- Contrast, non-color state cues, focus visibility, and reduced-motion behavior.

Automated tests should validate view-model mapping, permission behavior, resolution links, action availability, and durable submission states. Browser tests should validate the critical owner annual loop and reviewer-comment flow against real backend-shaped fixtures or the configured test environment, never demo-only UI state.

## Implementation references

The implementation should load:

- `reference/layout.md` for the shell, overview, and responsive hierarchy.
- `reference/harden.md` for filing failures, permissions, unsupported cases, and submission recovery.
- `reference/adapt.md` for mobile and narrow-screen structure.
- `reference/clarify.md` for Norwegian filing, warning, and error copy.
- `reference/onboard.md` for the first-year empty state.
- `reference/polish.md` for the final pre-ship pass.

## Open questions

No design question currently blocks implementation planning. Exact route boundaries, component interfaces, and migration sequencing belong in the implementation plan.
