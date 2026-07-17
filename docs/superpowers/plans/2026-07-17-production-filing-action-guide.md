# Production Filing Action Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a one-page checklist and a plain-language action guide for completing every gate before, during, and after Talli's first controlled RF-1086 production filing.

**Architecture:** Keep the checklist short and use it as the control sheet. Put full instructions, evidence rules, pass criteria, and stop conditions in the detailed guide. Add a Node test that keeps both documents linked and prevents required gates or safety rules from being removed later.

**Tech Stack:** Markdown, Node.js built-in test runner, existing npm scripts.

## Global Constraints

- Scope is one founder-assisted RF-1086 pilot using the exact `rf1086_no_activity_v1` profile.
- Production filing remains disabled until every required gate passes.
- Use short sentences, familiar words, and one action per numbered instruction.
- Start actions with clear verbs such as `Open`, `Check`, `Save`, `Ask`, `Record`, or `Stop`.
- Explain technical or legal terms once, but preserve exact system labels, database keys, environment variable names, and status codes.
- Do not copy tokens, private keys, raw personal data, or raw filing XML into evidence.
- An unknown write outcome must stop and must never cause a blind retry.
- `TALLI_AUTHORITY_OPS_ENABLED` and `TALLI_RF1086_PRODUCTION_ENABLED` stay `false` outside their separately approved windows.
- Do not describe annual accounts, company tax returns, corrections, expanded RF-1086 profiles, or public self-service filing as unlocked.

---

## File Map

- Create `tests/production_filing_action_guide.test.mjs`: document contract for stage coverage, release keys, switch safety, plain language, and cross-links.
- Modify `package.json`: add `test:production-filing-guide` and include it in `test:launch-rehearsal`.
- Create `docs/launch/production-filing-action-guide.md`: detailed instructions and evidence rules for all 15 stages.
- Create `docs/launch/production-filing-checklist.md`: short control sheet linking to every detailed stage.

### Task 1: Add the documentation contract

**Files:**
- Create: `tests/production_filing_action_guide.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: the approved design in `docs/superpowers/specs/2026-07-17-production-filing-action-guide-design.md`.
- Produces: `npm run test:production-filing-guide`, which later tasks use as their acceptance test.

- [ ] **Step 1: Create the failing document test**

Create `tests/production_filing_action_guide.test.mjs` with this content:

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const checklist = readFileSync(
  new URL("../docs/launch/production-filing-checklist.md", import.meta.url),
  "utf8",
);
const guide = readFileSync(
  new URL("../docs/launch/production-filing-action-guide.md", import.meta.url),
  "utf8",
);

const requiredStageSlugs = [
  "approve-the-legal-pack",
  "verify-hosted-tenant-isolation-and-private-storage",
  "complete-a-fresh-production-backup-and-restore-rehearsal",
  "verify-monitoring-incident-response-and-rollback",
  "select-an-eligible-pilot-company",
  "capture-business-terms-and-dpa-acceptance",
  "compare-talli-and-fiken",
  "verify-the-production-systemregister-callback",
  "complete-systembruker-approval-and-preflight",
  "record-the-required-launch-signoffs",
  "create-the-pilot-entitlement-and-billing-path",
  "capture-the-owners-final-approval",
  "run-the-production-filing-window",
  "save-the-final-result-and-closeout-evidence",
  "make-the-post-pilot-decision",
];

test("checklist links to every ordered action-guide stage", () => {
  for (const slug of requiredStageSlugs) {
    assert.match(checklist, new RegExp(`production-filing-action-guide\\.md#${slug}`));
    assert.match(guide, new RegExp(`id=\\"${slug}\\"`));
  }
});

test("guide keeps every runtime signoff and case-specific release gate", () => {
  for (const key of [
    "launch_legal_name_public_copy",
    "legal_policy_pack",
    "security_restore",
    "billing_refund",
    "support_rollback",
    "rf1086_authority",
    "founder_production_go_live",
    "rf1086_no_activity_v1",
    "billing_exempt=true",
  ]) {
    assert.match(guide, new RegExp(key));
  }
});

test("guide preserves switch, evidence, and unknown-outcome stop rules", () => {
  assert.match(guide, /TALLI_AUTHORITY_OPS_ENABLED=false/);
  assert.match(guide, /TALLI_RF1086_PRODUCTION_ENABLED=false/);
  assert.match(guide, /Do not use a real filing as a connection test\./i);
  assert.match(guide, /Do not send again\./i);
  assert.match(guide, /transport reference is not final acceptance/i);
  assert.match(guide, /Do not save tokens, private keys, raw personal data, or raw filing XML/i);
});

test("guide states its narrow scope and plain-language purpose", () => {
  assert.match(guide, /one controlled RF-1086 production pilot/i);
  assert.match(guide, /Use this guide one stage at a time/i);
  assert.match(guide, /Stop here\. Do not enable production filing\./i);
  assert.doesNotMatch(guide, /production filing is now generally available/i);
});
```

- [ ] **Step 2: Run the test and confirm it fails because the two documents do not exist**

Run:

```bash
node --test tests/production_filing_action_guide.test.mjs
```

Expected: FAIL with `ENOENT` for `docs/launch/production-filing-checklist.md`.

- [ ] **Step 3: Add the npm script**

Add this script next to the other launch and legal scripts in `package.json`:

```json
"test:production-filing-guide": "node --test tests/production_filing_action_guide.test.mjs"
```

Insert `npm run test:production-filing-guide` in `test:launch-rehearsal` after
`npm run test:filing-release-gate` and before `npm run test:launch-copy`.

- [ ] **Step 4: Confirm the npm command has the same expected failure**

Run:

```bash
npm run test:production-filing-guide
```

Expected: FAIL with `ENOENT` for the missing checklist.

- [ ] **Step 5: Commit the failing contract**

```bash
git add package.json tests/production_filing_action_guide.test.mjs
git commit -m "test: define production filing guide contract"
```

### Task 2: Write the detailed action guide

**Files:**
- Create: `docs/launch/production-filing-action-guide.md`
- Test: `tests/production_filing_action_guide.test.mjs`

**Interfaces:**
- Consumes: the 15 required slugs and phrases from Task 1; existing release rules from `app/lib/filing-release-gate.ts`, `docs/legal/README.md`, `docs/security/backup-restore-runbook.md`, and `docs/filing/rf1086-production-pilot-runbook.md`.
- Produces: one stable anchor and complete operating instructions for every checklist row.

- [ ] **Step 1: Add the guide introduction and status box**

Create `docs/launch/production-filing-action-guide.md`. Start it with:

```markdown
# Production filing action guide

Status: production filing is off
Scope: one controlled RF-1086 production pilot

Use this guide one stage at a time. Do not skip a stage. A later stage does not
fix a missing earlier stage.

This guide does not approve a filing. It explains how to collect the proof and
approvals that Talli requires before the first filing.

Start with the [one-page checklist](./production-filing-checklist.md).

> **Stop rule:** If a required check is missing, old, unclear, or rejected, stop
> here. Do not enable production filing.

> **Evidence rule:** Do not save tokens, private keys, raw personal data, or raw
> filing XML in an evidence document.
```

Add a short glossary for `evidence`, `signoff`, `AAL2`, `Systembruker`, `pilot
entitlement`, and `unknown outcome`. Define each in one sentence.

- [ ] **Step 2: Write stages 1–4 for legal and hosted safety**

Use explicit HTML anchors matching Task 1 before each heading. Use the ten-part
stage template from the approved design. Include these exact decisions:

| Stage | Required pass facts | Required stop facts | Runtime record |
| --- | --- | --- | --- |
| Legal pack | Founder approves commercial terms and subprocessors; legal reviewer approves acceptance, DPA, legal bases, retention, liability, transfers, governing law, and jurisdiction; security reviewer approves stated measures against hosted facts | Any draft point remains unresolved; reviewer or evidence link is missing | `legal_policy_pack`; also confirm `launch_legal_name_public_copy` |
| Tenant isolation/private storage | Test two real non-customer accounts against the deployed environment; prove cross-company rows, metadata, bytes, signed URLs, and private feedback are denied | Any cross-tenant read or private-object access works; deployed SHA is unknown | Evidence feeds `security_restore` |
| Backup and restore | Restore to an isolated target; compare required rows, object counts, byte sizes, and SHA-256 hashes; record target, operator, start/end, result | Restore touches live data; hashes differ; evidence is over 30 days old | `security_restore` |
| Monitoring and rollback | Name on-call owner; prove alerts, safe logs, kill switches, Vercel rollback, database recovery, and alternative filing route | Logs leak restricted data; no observer or fallback exists; switch state cannot be verified | `support_rollback` |

Each stage must say what evidence file or link to save, who reviews it, and what
the next stage is.

- [ ] **Step 3: Write stages 5–7 for the pilot company**

Include these rules:

| Stage | Required pass facts | Required stop facts | Record |
| --- | --- | --- | --- |
| Eligible company | Exact company, owner, income year, and `rf1086_no_activity_v1`; one share class; Norwegian shareholders; no purchase, sale, dividend, correction, or unsupported complexity | Any excluded fact is present or uncertain | Signed eligibility review |
| Terms and DPA | Authorized representative accepts current pinned versions and digests; acceptance evidence exists for the named company | Acceptance is missing, stale, fabricated, or made by someone without authority | Immutable agreement acceptance |
| Talli and Fiken | Generate the same period and facts; compare every material figure and document; resolve differences; get named accounting review or written risk acceptance | Inputs differ; unexplained material difference remains; reviewer will not approve | Comparison table and reviewer decision |

State that named-company data must not be uploaded until legal approval and
hosted tenant-isolation/private-storage/restore evidence are current.

- [ ] **Step 4: Write stages 8–12 for authority and approval**

Include these rules:

| Stage | Required pass facts | Required stop facts | Runtime record |
| --- | --- | --- | --- |
| Callback | Fresh AAL2 window; enable only the fixed callback operation; exact GET returns `callback_already_verified` or `callback_updated_and_verified`; switch returns to false | Callback differs, result is not allowlisted, or switch cannot be confirmed false | Redacted authority-operation audit |
| Systembruker | Customer approves the exact request; read-only preflight confirms company, user, right, and external reference | Pending/duplicate request, identity mismatch, failed preflight, or lost delegation | Accepted and verified Systembruker request |
| Signoffs | Record reviewer, date, evidence link, and decision for every required key | Any key is missing, rejected, or `security_restore` is stale | All required `launch_signoffs` |
| Entitlement | Exact company/user/year/obligation/profile and short validity window; use `billing_exempt=true` for the free pilot or complete billing/refund proof | Entitlement is broad, expired, mismatched, or created before preflight | Production pilot entitlement |
| Owner approval | Owner uses fresh AAL2; reads exact preview; approves payload, document, and adapter hashes | Preview changes, AAL2 is stale, or hash is different | Immutable production approval |

List all seven RF-1086 signoff keys. Explain plainly that `billing_refund` may be
skipped only when the exact active pilot entitlement has `billing_exempt=true`.

- [ ] **Step 5: Write stages 13–15 for filing and closeout**

Include these rules:

| Stage | Required pass facts | Required stop facts | Record |
| --- | --- | --- | --- |
| Filing window | Name operator, owner, observer, deadline, alternative route, and approved window; verify every gate; enable filing only for that window; send once | Any gate changes, entitlement mismatches, kill switch is unavailable, or unexpected endpoint appears | Journal and operator case |
| Final result | Treat `received` and `processing` as incomplete; archive official final `accepted` or `rejected` feedback and receipt; return both switches to false | Outcome is `unknown`; artifact persistence fails; final feedback is absent | Closeout evidence package |
| Post-pilot | Review result, incidents, support load, discrepancies, and restored evidence before deciding to stop or repeat | Do not expand after one transport reference or unresolved issue | Written founder/reviewer decision |

Use these exact instructions in the unknown-outcome path:

```text
Stop the filing window.
Set both production switches to false.
Do not send again.
Keep the idempotency record and journal.
Reconcile the result through read-only authority calls and support.
```

State plainly that a transport reference is not final acceptance.

- [ ] **Step 6: Run the guide test**

Run:

```bash
npm run test:production-filing-guide
```

Expected: FAIL only because the one-page checklist is still missing.

- [ ] **Step 7: Commit the detailed guide**

```bash
git add docs/launch/production-filing-action-guide.md
git commit -m "docs: add production filing action guide"
```

### Task 3: Write the one-page checklist

**Files:**
- Create: `docs/launch/production-filing-checklist.md`
- Test: `tests/production_filing_action_guide.test.mjs`

**Interfaces:**
- Consumes: the 15 stable anchors from Task 2.
- Produces: the founder's short control sheet and the final passing documentation contract.

- [ ] **Step 1: Add the checklist header and use rules**

Start the checklist with:

```markdown
# First production filing checklist

Status: production filing is off
Scope: one controlled RF-1086 production pilot

Use this page to track the work. Follow each link for the full instructions.
Complete the rows in order. Do not mark a row `Passed` without an evidence link,
a named reviewer, and a review date.

Allowed status values: `Not started`, `In progress`, `Blocked`, `Passed`.

> If any row is not `Passed`, stop here. Do not enable production filing.
```

- [ ] **Step 2: Add all 15 checklist rows**

Create one table with these columns:

```markdown
| # | Stage | Owner | Status | Evidence | Reviewer and date |
| --- | --- | --- | --- | --- | --- |
```

Add one row for each Task 1 slug, in order. The stage text must link to
`./production-filing-action-guide.md#<slug>`. Use these default owners:

1. Founder + legal + security
2. Security reviewer
3. Security reviewer + operator
4. Operator + on-call observer
5. Founder + accounting reviewer
6. Customer representative + founder
7. Founder + accounting reviewer
8. Founder/operator
9. Customer owner + founder/operator
10. Named reviewers + founder
11. Founder/operator
12. Customer owner
13. Founder/operator + customer owner + observer
14. Founder/operator + observer
15. Founder + named reviewers

Set every initial status to `Not started`. Leave evidence and reviewer cells as
`—`; these are intentional blanks for the real pilot, not hidden approvals.

- [ ] **Step 3: Add the final ready-to-file box**

End with checkboxes for:

- every row is `Passed`;
- `security_restore` is no more than 30 days old;
- the exact entitlement is active;
- owner AAL2 and approval are fresh;
- both switches are false before the approved window;
- the observer, kill switch, and alternative route are ready; and
- `founder_production_go_live` was recorded after the supporting evidence.

End with: `Only the named founder/operator may start the approved filing window.`

- [ ] **Step 4: Run the focused test**

Run:

```bash
npm run test:production-filing-guide
```

Expected: PASS, 4 tests, 0 failures.

- [ ] **Step 5: Commit the checklist**

```bash
git add docs/launch/production-filing-checklist.md
git commit -m "docs: add production filing checklist"
```

### Task 4: Verify the complete documentation change

**Files:**
- Verify: `docs/launch/production-filing-action-guide.md`
- Verify: `docs/launch/production-filing-checklist.md`
- Verify: `tests/production_filing_action_guide.test.mjs`
- Verify: `package.json`

**Interfaces:**
- Consumes: all deliverables from Tasks 1–3.
- Produces: evidence that the documentation is internally linked, fail-closed, plain, and included in the release rehearsal.

- [ ] **Step 1: Scan for placeholders and needlessly formal wording**

Run:

```bash
rg -n "TBD|TODO|FIXME|utilize|facilitate|leverage|operationalize" \
  docs/launch/production-filing-checklist.md \
  docs/launch/production-filing-action-guide.md
```

Expected: no output. Intentional `—` cells in the checklist are allowed.

- [ ] **Step 2: Check all local Markdown links**

Run a read-only link check that extracts relative `.md` targets from both files
and confirms that each target exists relative to its source file.

Expected: every target exists.

- [ ] **Step 3: Run focused release tests**

```bash
npm run test:production-filing-guide
npm run test:filing-release-gate
npm run test:launch-signoff
npm run test:legal-policy
```

Expected: all commands exit 0.

- [ ] **Step 4: Run formatting and repository checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; status shows only the intended guide, checklist,
test, and `package.json` changes if any are not yet committed.

- [ ] **Step 5: Review the final diff against the approved design**

Confirm all 15 stages, ten template fields, seven signoff keys, evidence rules,
switch rules, narrow scope, and plain-language rules are present. Confirm no text
claims production filing is currently enabled.

- [ ] **Step 6: Commit any verification-only correction**

If Step 5 required a correction:

```bash
git add docs/launch/production-filing-checklist.md \
  docs/launch/production-filing-action-guide.md \
  tests/production_filing_action_guide.test.mjs package.json
git commit -m "docs: tighten production filing guide safeguards"
```

If no correction was required, do not create an empty commit.
