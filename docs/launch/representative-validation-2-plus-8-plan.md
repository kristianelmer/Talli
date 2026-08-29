# Representative Validation: Approved 2+8 Design

Status: founder-approved design; recruitment, named data and production actions
remain separately gated

Decision date: 2026-08-29

Owning issue: #197

## Purpose

Validate that Talli's supported boundary and complete customer journey work for
real eligible holding-company years. This is purposive acceptance evidence, not a
statistical claim about every Norwegian holding company.

## Entry Gate

Do not recruit or accept named-company data until #196 closes and the pinned
participant terms/DPA, lawful channel, hosted isolation/storage, MFA, logging,
backup/restore, retention/export/delete, incident handling and named contacts are
approved and current. Provider calls, charges and filings keep their own gates.

The no-contact preparation materials are in
`representative-validation-pre-intake-pack.md`. Completing blank templates or
local checks in that pack does not open this entry gate, claim #197 or authorize
outreach or data intake.

## Temporary Higher-Resolution Observation Mode

The founder approved a separate test-only observation mode for the invited 2+8
validation run. Its purpose is to produce a definitive product-sufficiency
decision, not to enlarge public marketing analytics.

The invited pilot uses the exact normal production product. The build, UI,
eligibility and accounting rules, authorization, capability gates, provider
adapters, persistence, errors and customer workflow must be identical with the
observer on or off. There are no pilot-only shortcuts, mock outcomes, relaxed
checks or alternate product branches. The setting controls only a passive
bounded log written after the normal product outcome.

The future implementation must be deny-by-default with only `off` and
`invited-pilot` states. `invited-pilot` must require a server-side named pilot
entitlement, approved validation run ID and automatic expiry. It must not be
enabled by a URL, browser setting or client-supplied request field. Full public
launch requires immutable evidence that the mode is `off` and every pilot
entitlement has expired or been revoked.

Use `V-01` through `V-12` in evaluation records. The identity mapping remains in
the approved protected participant register. Bounded observations may record:

- critical task started, completed, failed or blocked;
- bounded stage and reason codes;
- elapsed task time;
- intervention type, count and duration;
- difference/defect classification and rerun result; and
- bounded final package outcome for RF-1086, company tax and annual accounts.

Do not put identity, contact details, organization number, free text, document or
bank contents, filenames, ledger values, exact monetary amounts, or marketing
source attribution in this evaluation stream. Participant information,
agreement, retention, access, withdrawal, export and deletion behavior must be
approved before observation starts. This mode remains blocked by the same entry
gate as all named pilot data.

An observation-write failure must not change, roll back, retry or hide the
product result. It makes the affected test evidence incomplete, so the evidence
must be recovered or the normal action rerun before acceptance. Before intake,
run the same representative actions with observation `off` and `invited-pilot`;
responses, business-state writes and external calls must match exactly, with the
bounded observation-log write as the sole permitted difference.

## Phase 1 — Two Anchors

Use two overlapping eligible cases:

1. one closed historical company-year with strong incumbent ledger, source and
   filed-output evidence; and
2. one current-year company with live read-only banking plus CSV/CAMT.053 fallback.

Use them to calibrate evidence capture, difference classification, independence,
support timing, withdrawal/export/delete, incidents and the ledger-to-filings-to-
archive trace. Fix and rerun material defects before expanding.

## Phase 2 — Eight Varied Company-Years

Add eight independently operated eligible cases, targeting ten completed packages
in total. Across real and golden evidence, cover every accepted common pattern at
least twice, including:

- new/no-activity/opening/January and at least three mid-year reconstructions;
- one and multiple Norwegian shareholders;
- supported private/listed investment purchases, sales, dividends, gains/losses;
- ordinary capital changes and loss coverage;
- bank, owner and intercompany debt and group contributions;
- interest, tax and administrative costs; and
- varied launch banks, automatic sync and structured-file recovery.

Run six sanitized near-boundary rejections for audit/consolidation, operating
activity, foreign or unclear tax, company-to-person loans, complex finance or
reorganization, and incomplete reconstruction. Rejections do not count among the
ten completed company-years.

## Evidence and Pass Rules

- Participants make every accounting decision and operate Talli themselves.
- Compare bank/source evidence, incumbent ledger/SAF-T, corporate documents and
  all filed outputs.
- Classify every difference as Talli defect, source defect, presentation-only or
  unresolved judgment; fix/rerun defects.
- Every critical journey completes.
- At least 90% of core tasks complete without intervention.
- Median support is below 30 minutes per company-year.
- Talli staff/agents exercise no customer-specific accounting judgment.
- Zero unexplained material differences, incidents or duplicates remain.
- Genuine final outcomes exist for RF-1086, company tax and annual accounts.
- The temporary observation mode supplies a complete bounded case matrix for the
  decision and is proven `off` before full public launch.

Extend to 12 company-years if any accepted pattern is covered only once, a
difference remains unstable, or support/confusion thresholds are not settled.

## Stop Rules

Stop affected intake or consequential actions on a failed legal, privacy,
isolation, authority, provider, accounting, filing, security or UX gate. Preserve
read/export access, honor withdrawal/delete obligations, record the incident or
unsupported exit, fix the owning capability and rerun the affected evidence.

Approval of this design does not authorize recruitment, outreach, customer data,
provider activation, a charge, a production filing or public launch.
