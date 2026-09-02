# Hosted Processors, Transfers and Backup — Issue #196 Decision Package

Status: research complete; no provider upgrade, contract acceptance, credential
rotation, production deployment, or legal approval performed

Research date: 2026-08-31

Scope: the exact Talli Vercel and Supabase targets recorded in
[`hosted-facts-2026-08-31.json`](../../architecture/evidence/issues/196/hosted-facts-2026-08-31.json),
checked against current first-party Vercel and Supabase documentation, pricing,
DPAs, subprocessor material, region documentation, logging limits and backup
documentation.

This package separates provider statements, observed Talli facts, inferences and
human decisions. It is not legal advice and does not determine GDPR compliance,
transfer law, processor suitability, security acceptance or production readiness.

## Executive decision state

The evidence supports one narrow conclusion: **keep unrestricted production
activation blocked**.

- Talli's current Vercel team is on Hobby. Vercel limits Hobby to personal,
  non-commercial use, so a commercial Talli launch cannot remain on that plan.
  Vercel Pro currently starts at **USD 20/month** for one deploying seat, includes
  USD 20/month of usage credit, and becomes usage-billed after the included
  amounts. Sources: [Hobby plan](https://vercel.com/docs/plans/hobby),
  [Pro plan](https://vercel.com/docs/plans/pro-plan), and
  [pricing](https://vercel.com/pricing).
- Talli's current Supabase organization is on Free. Supabase Free has no automatic
  backups or point-in-time recovery. Pro currently starts at **USD 25/month** for
  the first project and includes daily database backups retained for seven days;
  usage above included allowances can add charges. Sources:
  [pricing](https://supabase.com/pricing) and
  [database backups](https://supabase.com/docs/guides/platform/backups).
- A Vercel Pro plus Supabase Pro baseline is therefore **USD 45/month recurring**
  before taxes, currency conversion, overages, additional seats, log drains,
  observability add-ons, PITR or higher support/compliance plans. This is an
  arithmetic inference from the two current price pages, not a provider quote.
- The exact current Vercel preview executes in Dublin (`dub1`) and the exact
  Supabase project stores primary data in AWS Ireland (`eu-west-1`). The existing
  public production deployment still executes in Washington, D.C. (`iad1`). These
  are observed deployment facts, not proof that all processing stays in Ireland.
- Neither a plan upgrade nor matching compute/database regions resolves the
  outstanding human legal/privacy/security decisions. Vercel's current DPA says
  its primary processing facilities are in the United States and contemplates
  processing wherever it or its subprocessors operate. Supabase likewise presents
  region selection as a data-location control, not proof of regulatory compliance.
  Sources: [Vercel DPA](https://vercel.com/legal/dpa) and
  [Supabase regions](https://supabase.com/docs/guides/platform/regions).
- Supabase now publishes a canonical, live **Version 1 — August 1, 2026** DPA
  through its Legal Hub. Supabase's current Terms of Service define that document
  as the DPA, incorporate it into the online Agreement and make the Agreement
  effective through acceptance or use. This resolves the earlier document-
  availability gap; it does not prove which legal person accepted the exact Talli
  account's Agreement, that the accepter had authority to bind Talli, or that a
  human reviewer accepts the DPA and transfer terms. Sources:
  [Supabase DPA](https://supabase.com/legal/customer-resources/data-processing-addendum)
  and [Terms of Service](https://supabase.com/terms).

No spend is authorized by this package. The repository cost guardrail requires
explicit approval before any upgrade or usage-based service is enabled.

## 1. Exact observed Talli state

The statements in this section come from the immutable hosted audit, not from
provider marketing pages.

| Area | Verified Talli fact | Consequence for #196 |
| --- | --- | --- |
| Vercel target | Team `team_vjY7Lg3yOS7gSUnFqbihoTo2`, project `prj_1JJkOqzGBhn438IKHYADWiRbVGeZ`, plan `hobby` | Commercial hosting gate is red while Talli remains on Hobby |
| Current source preview | Revision `250c0c4ed648b4135338938b1dddd4e7647ea605`, deployment `dpl_EB2oDn7o9vA4E4KurGc4mUUWZmrG`, READY in `dub1` | Demonstrates the current source can deploy in Ireland; it is not a production authorization |
| Existing public production | Revision `d331ee2717d1eeacef0d81db42b9d4fb5848b408`, deployment `dpl_HuHzBsgpcgBVTGsFiFLEEy3PqN5f`, READY in `iad1` on `talli.no`/`www.talli.no` | Public production remains an older, invitation-only free beta in a US function region |
| Vercel secrets | Five database-related environment-variable names exist for Production and Preview, but their saved values are write-only and predate creation of the designated Supabase project | Binding the app to the exact database is unverified; controlled secret rotation requires human confirmation at transmission time |
| Supabase target | Organization `zwucumjvtpnyujqyzwkg`, project `pkpyyxryfhfehrbhbynp`, Free, ACTIVE_HEALTHY, Postgres 17.6, `eu-west-1` | The exact database is identified and Ireland-hosted, but Free-plan reliability limits remain |
| Database release | 47 migrations applied; the last is `20260830091341_case_bound_support_access`; legal migration `20260830093000_current_legal_evidence` remains held | Legal publication remains serialized behind the billing/unreachable-path decision |
| Launch-off state | Observer mode `off`; zero active validation entitlements, marketing releases, marketing consent actions and marketing events | The hosted target is fail-closed for participant and marketing activation |
| Current data | Zero auth users, companies, memberships, storage objects, validation records and support grants | There is no current customer dataset to recover, but this does not prove a production backup design |
| Data controls | All 53 public tables have RLS enabled | Useful technical evidence; not a processor, transfer, backup or human-approval substitute |
| Current monitoring | Vercel: no runtime errors in the available window, 60 HTTP 200 and two HTTP 204 preview responses; Supabase logs were queryable only within the Free retention window | A short clean window is not historical reliability or incident-response evidence |

Canonical evidence:
[`architecture/evidence/issues/196/hosted-facts-2026-08-31.json`](../../architecture/evidence/issues/196/hosted-facts-2026-08-31.json).

## 2. Verified provider facts

### 2.1 Vercel plan, observability and reliability boundaries

1. Vercel's Hobby plan is free and restricted to non-commercial, personal use.
   Its terms also reserve broad rights to disable Hobby projects. Sources:
   [Hobby plan](https://vercel.com/docs/plans/hobby) and
   [Terms of Service, section 4](https://vercel.com/legal/terms).
2. Pro is positioned for professional and business use. Its current platform fee
   is USD 20/month, includes one deploying seat and USD 20/month of usage credit,
   and moves to on-demand billing after included usage/credit. Sources:
   [Pro plan](https://vercel.com/docs/plans/pro-plan) and
   [pricing](https://vercel.com/pricing).
3. Runtime-log retention is one hour on Hobby, one day on Pro, and 30 days on Pro
   with Observability Plus. Vercel lists Observability Plus at USD 10/month. Log
   drains are available on Pro, with drain volume priced separately on the
   pricing page. Sources: [runtime logs](https://vercel.com/docs/logs/runtime),
   [Pro plan](https://vercel.com/docs/plans/pro-plan), and
   [pricing](https://vercel.com/pricing).
4. Vercel's public pricing places a 99.99% SLA under Enterprise, not Hobby or Pro.
   Therefore a Pro upgrade is not itself evidence of a binding uptime SLA.
   Source: [pricing](https://vercel.com/pricing).
5. Vercel Functions default to `iad1` in Washington, D.C. A project can select a
   region, and `dub1` maps to Dublin, Ireland. Vercel recommends placing functions
   close to their data source. Sources:
   [function region configuration](https://vercel.com/docs/functions/configuring-functions/region)
   and [regions](https://vercel.com/docs/regions).

### 2.2 Vercel DPA and subprocessors

1. Vercel's current DPA is dated 17 March 2026 and effective 31 March 2026. It
   expressly applies to processor activity for **Pro and Enterprise** customers;
   it does not state that its processor terms apply to Hobby. Source:
   [Vercel DPA, introduction](https://vercel.com/legal/dpa).
2. The DPA describes Vercel as processor for customer data and controller for
   service-generated/contact data, with the exact role depending on the data.
   It also assigns the customer responsibility for lawful instructions, notices
   and consents. Source: [Vercel DPA, sections 4–6](https://vercel.com/legal/dpa).
3. The DPA states that Vercel's primary processing facilities are in the United
   States and that data may be processed in the United States and elsewhere that
   Vercel or subprocessors operate. It incorporates the 2021 EU Standard
   Contractual Clauses for covered transfers and selects Irish law/courts for the
   stated SCC provisions. Source:
   [Vercel DPA, section 13 and schedule 3](https://vercel.com/legal/dpa).
4. Vercel publishes a dynamic subprocessor list through its Trust Center. The DPA
   requires customers to subscribe for notices and provides a five-calendar-day
   objection window based on reasonable data-protection concerns; unresolved
   objections may leave termination as the stated remedy, without refund of
   committed fees. Sources: [Vercel DPA, section 7](https://vercel.com/legal/dpa)
   and [Vercel Trust Center](https://security.vercel.com/).
5. The DPA tells customers to make their own security-suitability determination
   and maintain their own backups of customer data. Source:
   [Vercel DPA, section 8](https://vercel.com/legal/dpa).

### 2.3 Supabase plan, logs, access and backup boundaries

1. Supabase Free is USD 0/month, pauses after one week of inactivity, retains API
   and database logs for one day, excludes log drains, automatic backups, PITR,
   Platform Audit Logs and uptime SLAs, and offers Owner/Admin/Developer roles.
   Source: [pricing comparison](https://supabase.com/pricing).
2. Supabase Pro starts at USD 25/month for the first project. It includes daily
   backups retained seven days and seven-day logs. It does **not** add the
   Read-Only/platform-audit controls that Supabase reserves for higher tiers.
   Source: [pricing](https://supabase.com/pricing).
3. Supabase says Platform Audit Logs and the Read-Only organization/project role
   are available only on Team and Enterprise. Team currently starts at USD
   599/month. Sources:
   [Platform Audit Logs](https://supabase.com/docs/guides/security/platform-audit-logs),
   [access control](https://supabase.com/docs/guides/platform/access-control), and
   [pricing](https://supabase.com/pricing).
4. Supabase automatically backs up Pro, Team and Enterprise projects daily. It
   recommends that Free projects run `supabase db dump` and retain off-site
   backups. Database backups do not include Storage API object bodies—only their
   database metadata—so objects need a separate backup path. Source:
   [database backups](https://supabase.com/docs/guides/platform/backups).
5. Supabase now documents a no-password temporary-access route for projects on
   Postgres 17.6.1.081 or later. An Owner/Admin must first enforce incoming SSL,
   enable temporary access, map a project member to an existing database role and
   set any expiry/IP restrictions; the member's Personal Access Token is then used
   as that role's database password. The exact Talli project reports Postgres
   `17.6.1.166`, so it is version-eligible. This can provide a least-duration
   credential for a manual `db dump` without resetting or disclosing the durable
   database password, but enabling the feature and granting the role are still
   privileged access mutations requiring explicit authorization. Sources:
   [temporary access](https://supabase.com/docs/guides/platform/temporary-access)
   and [feature announcement](https://supabase.com/changelog/46346-feature-preview-temporary-token-based-database-access).
6. Supabase currently lists PITR from USD 100/month for seven days of recovery
   retention. PITR is optional and is not included in the USD 25/month Pro base.
   Sources: [database backups](https://supabase.com/docs/guides/platform/backups)
   and [pricing](https://supabase.com/pricing).
7. Supabase Log Drains require Pro, Team or Enterprise. The current pricing page
   lists an additional USD 60 per drain per project. Sources:
   [Log Drains](https://supabase.com/docs/guides/monitoring-and-debugging/log-drains)
   and [pricing](https://supabase.com/pricing).
8. Supabase documents a shared-responsibility model: the customer remains
   responsible for its account, access management, data, security controls and
   secret handling. Sources:
   [shared responsibility](https://supabase.com/docs/guides/deployment/shared-responsibility-model)
   and [secure data](https://supabase.com/docs/guides/database/secure-data).
9. Each Supabase project has one primary region, and a specific `eu-west-1`
   selection means West EU (Ireland) for primary project data. Supabase cautions
   that region selection is a data-location control, not regulatory-compliance
   proof. Source: [regions](https://supabase.com/docs/guides/platform/regions).

### 2.4 Supabase DPA and subprocessors

1. Supabase's canonical Legal Hub now links a live HTML DPA at
   [`/legal/customer-resources/data-processing-addendum`](https://supabase.com/legal/customer-resources/data-processing-addendum).
   It identifies itself as **Version 1 — August 1, 2026**, supplements and forms
   part of the Supabase Terms of Service or another relevant customer agreement,
   and is effective on the Agreement's effective date. The current Terms define
   this URL as the “Data Processing Addendum,” state that the parties agree to
   comply with it and incorporate it into the Agreement. The Terms state that the
   Agreement becomes effective when the customer clicks acceptance or accesses or
   uses the Services. Sources: [Legal Hub](https://supabase.com/legal),
   [DPA](https://supabase.com/legal/customer-resources/data-processing-addendum),
   and [Terms of Service](https://supabase.com/terms).
2. The DPA identifies Supabase Pte. Ltd. of Singapore as the contracting processor,
   sets its customer fields by reference to the information associated with the
   customer's Supabase account or other Agreement, and incorporates the 2021 EU
   SCCs. It states that acceptance of the Agreement has the same effect as signing
   the SCCs. It uses Modules Two or Three as applicable, Irish law and Irish courts
   for the specified EU SCC provisions, and permits Supabase and subprocessors to
   process anywhere they maintain facilities subject to its regional-processing
   and transfer terms. Source:
   [Supabase DPA](https://supabase.com/legal/customer-resources/data-processing-addendum).
3. Supabase publishes a canonical
   [Subprocessor List page](https://supabase.com/legal/customer-resources/subprocessor-list)
   which currently links a two-page
   [“Updated June 1, 2026” schedule](https://supabase.com/legal/subprocessor-list/June-1-2026.pdf).
   The schedule contains 24 named subprocessors and a purpose for each, including
   AWS and Google for hosting, Cloudflare/Fly.io/Vercel for hosting, Supabase Inc.
   for support, Sentry and Braintrust for monitoring/tracing, OpenAI for natural-
   language processing/generation, and providers used for support communications,
   authentication, analytics, security, status and serverless data hosting. It
   does **not** publish each subprocessor's processing country or facility location.
4. The subprocessor landing page says it is updated as subprocessors change and
   offers email-update subscriptions. Under DPA clause 6.3, a subscribed customer
   receives at least 30 days' notice of proposed changes and must object within
   five days after Supabase provides notice; an unresolved objection may permit
   termination of the affected Services. Sources:
   [Subprocessor List](https://supabase.com/legal/customer-resources/subprocessor-list)
   and [DPA clause 6](https://supabase.com/legal/customer-resources/data-processing-addendum#6-sub-processors).
5. Availability was rechecked on 2026-08-31 using direct first-party HTTP GETs.
   The Legal Hub, canonical DPA, subprocessor landing page and June 1 schedule all
   returned HTTP 200. The canonical DPA response was 100,958 bytes with SHA-256
   `1e7d3d3ad5d8b733dfd454ce72cacdcc30d245c93b2210606f1a97fc84d64e82`;
   the Terms response was 121,656 bytes with SHA-256
   `734b31aee9e424f276d68f2e747f879d80c744e1ba727a510fff692cbda9f34c`;
   and the schedule's downloaded bytes had SHA-256
   `e85324d3d26fd754755a8cbcf8ddf3f1e8b04f164eb4959a63e53f6aa3f5fa6d`.
   The two HTML hashes cover the complete raw HTTP response bodies as retrieved;
   dynamic site markup can change independently of the displayed legal version,
   so the version label and retrieval date remain the controlling human-readable
   identifiers.
   The formerly indexed March 2026, August 5, 2025 and December 11, 2023 PDF
   download URLs each returned HTTP 404. Those obsolete URLs are not the current
   agreement surface and should not be used as evidence that the DPA is
   unavailable.
6. The canonical document resolves the **obtainability** question and provides an
   online contractual incorporation route. It does not itself prove the exact
   Talli account's customer identity, the authority of the person who accepted or
   used the service, whether a separate agreement overrides the online terms, or
   human approval of the transfer/subprocessor terms. Those remain account and
   legal-review facts, not provider-document facts.

## 3. Inferences from the combined evidence

These are reasoned Talli conclusions, not provider promises or legal opinions.

1. **Dublin compute narrows but does not eliminate transfer scope.** The current
   preview's `dub1` function region aligns geographically with the `eu-west-1`
   database. It does not supersede Vercel's DPA language about US/global
   processing, the CDN, support/service-generated data or subprocessors.
2. **The older public production deployment remains a distinct transfer fact.**
   Until production is replaced by an approved immutable release, its `iad1`
   function execution remains US-hosted even though the new preview is in Dublin.
3. **Vercel Pro is a commercial-entry requirement if Vercel remains the host.**
   The free Hobby alternative can support non-commercial preview/evaluation only;
   it is not an unrestricted commercial launch path under Vercel's own terms.
4. **Supabase Pro solves only part of the reliability gap.** It adds seven daily
   database backups and seven-day logs, but it does not back up Storage object
   bodies, prove a restore rehearsal, provide PITR, provide Platform Audit Logs or
   provide the Read-Only dashboard role.
5. **A clean empty target lowers immediate recovery exposure but is not a launch
   control.** Zero current users/data means there is little current business data
   to lose. Once participant or customer intake begins, the absence of a tested
   database-and-object recovery path becomes material immediately.
6. **One-day/one-hour observation cannot establish reliability.** The current
   clean windows demonstrate only that the sampled requests did not show errors;
   they do not establish availability, incident response, RTO/RPO or durable audit
   evidence.
7. **A plan purchase is not an SLA.** The public pages place Vercel's 99.99% SLA
   and Supabase's uptime SLA under Enterprise offerings. Pro-plan purchase alone
   therefore cannot close a contractual-SLA requirement.
8. **Secret rotation is a separate authorization boundary.** Replacing Vercel's
   database variables with credentials for `pkpyyxryfhfehrbhbynp` would transmit
   sensitive credentials and mutate Production/Preview configuration. It requires
   action-time human confirmation and post-rotation proof before target binding can
   be marked verified.

## 4. Costed choices and free alternatives

All amounts are current public USD list prices, recurring monthly unless stated,
before tax, exchange effects and usage. None is approved.

| Choice | Current minimum | What it addresses | What it does not address |
| --- | ---: | --- | --- |
| Keep Vercel Hobby | USD 0 | Preview/non-commercial evaluation | Commercial use, Pro DPA applicability, durable logs, SLA |
| Vercel Pro | USD 20 + usage | Commercial-plan eligibility, current DPA applicability, one-day runtime logs, one deploying seat | Human legal review, transfer assessment, 30-day logs, uptime SLA |
| Vercel Pro + Observability Plus | USD 30 + usage | Above plus 30-day runtime-log retention | External archival design, audit review process, uptime SLA |
| Keep Supabase Free + manual backup | USD 0 provider-plan cost | Can use `supabase db dump` for an off-site logical database copy | Automation, protected off-site destination, Storage objects, tested restore, PITR, one-day logs, platform audit, read-only reviewer role, non-pausing production behavior |
| Supabase Pro | USD 25 + usage | Daily database backups/7-day retention, seven-day logs, non-pausing paid project | Storage-object backup, restore proof, PITR, Platform Audit Logs, Read-Only role, uptime SLA |
| Supabase Pro + PITR (7 days) | From USD 125 + usage | Above plus point-in-time database recovery | Storage-object backup, restore proof, platform audit/read-only role, uptime SLA |
| Supabase Team | From USD 599 + usage | Pro features plus Read-Only/project-scoped access, Platform Audit Logs, longer logs/backups and priority support | Talli-specific control operation, Storage-object backup, legal approval; confirm exact SLA separately |
| Vercel Pro + Supabase Pro baseline | USD 45 + usage | Minimum current paid combination for Vercel commercial eligibility and Supabase automated daily database backup | All remaining legal, transfer, object-backup, restore, SLA and human gates |

Free or cheaper paths that remain technically possible:

- Keep the application in invitation-only/non-commercial preview while the legal,
  provider and reliability gates remain red. This preserves the current USD 0
  plans but cannot become unrestricted commercial launch.
- On Supabase Free, create scheduled or operator-run `supabase db dump` exports,
  separately export private Storage objects, place both in an access-controlled
  off-site destination, define retention and deletion, and rehearse restoration.
  This may avoid the Supabase Pro fee, but credentials, automation, storage,
  monitoring and human operation still need an approved design; the destination
  itself may have a cost. For the database export, the exact Postgres 17 project
  can use Supabase's temporary-access feature with a narrowly timed role grant and
  PAT instead of resetting or disclosing the durable database password; that
  privileged grant still needs explicit authorization and revocation evidence.
- Move away from Vercel to a host whose current terms permit commercial use at no
  charge. No alternative host was evaluated in this package, so this is only a
  route to research, not an evidenced free substitute.
- Keep provider log windows short and emit minimized application audit events to a
  Talli-controlled store. This can reduce dependence on paid observability, but it
  creates its own personal-data, retention, security, monitoring and restore
  responsibilities and does not replace provider/platform audit logs.

## 5. Unresolved human decisions

These decisions cannot be completed by technical evidence alone.

### Commercial and cost authority

- Approve or reject Vercel Pro at USD 20/month plus usage for one deploying seat.
- Approve Supabase Pro at USD 25/month plus usage, or accept a fully specified and
  rehearsed manual Free-plan database-and-object backup design.
- Decide the required log-retention period. If 30 days of Vercel runtime logs is
  required, separately approve the USD 10/month Observability Plus add-on; if a
  drain is required, approve its provider and usage charges.
- Decide whether platform-level audit records and a true Read-Only reviewer role
  are launch requirements. If yes, Supabase's current public plan boundary points
  to Team from USD 599/month, not Pro.
- Decide whether PITR is required. If yes, approve Supabase's current price from
  USD 100/month for seven days in addition to a paid plan.

### Legal and privacy authority

- Determine Talli's controller/processor roles for each Vercel and Supabase data
  category, including service-generated data, support data, logs and backups.
- Obtain and execute the current applicable Vercel DPA. For Supabase, verify and
  preserve evidence that the exact Talli account's authorized legal customer is
  bound by the current online Agreement and incorporated Version 1 DPA (or identify
  any separate governing agreement); do not rely on the obsolete PDF URLs.
- Review, approve and pin dated subprocessor schedules for both providers. For
  Supabase, pin the June 1, 2026 schedule and its digest, subscribe the approved
  legal contact to updates if authorized, and obtain or assess the missing country/
  facility information alongside purposes, notice channels, objection windows and
  exit consequences.
- Determine whether the SCCs and any additional measures are sufficient for the
  actual Vercel/Supabase processing and support flows. Dublin function/database
  placement must not be treated as eliminating US or other onward processing.
- Approve exact purposes, data categories, retention/deletion, data-subject help,
  incident cooperation, government-access handling and termination/return terms.
- Decide whether the old `iad1` production deployment must be removed, preserved
  only for rollback, or replaced under an approved release and transfer record.

### Security and reliability authority

- Confirm the approved Vercel/Supabase owners, administrators and reviewers;
  enforce MFA and document break-glass/recovery access.
- Authorize controlled rotation of all database-related Vercel secrets to the exact
  owner-designated Supabase project, then verify Preview and Production separately
  without exposing secret values.
- For the Free-plan manual database backup, authorize either a narrowly timed
  temporary-access role grant using an expiring PAT or another approved database
  credential route; define who creates, handles and revokes that access.
- Define RPO, RTO, maximum backup age, retention, restore destination, encryption,
  access review, deletion and evidence requirements for both Postgres and Storage
  object bodies.
- Perform and independently witness a real restore rehearsal. A provider backup
  listing or an empty database is not a restore test.
- Define durable incident evidence: minimum log windows, application audit events,
  alerts, on-call ownership, escalation, communications, provider status evidence
  and post-incident review.
- Decide whether public provider terms without a binding uptime SLA satisfy the
  launch reliability bar. If not, obtain the required contract/plan or choose a
  different architecture.

### Final product authority

- Confirm that participant intake, marketing activation, paid admission, charging,
  bank sync and filings remain disabled until their separately serialized gates
  pass.
- Approve the exact immutable production candidate only after the legal, privacy,
  security, restore, processor, transfer, billing and provider evidence refers to
  the same deployed revision and configuration.

## 6. Evidence-led route to close the #196 hosted lane

This sequence is a recommendation, not an authorization:

1. Preserve the current launch-off state and exact audit JSON.
2. Obtain explicit cost authority for the selected plans/add-ons, or document the
   accepted free alternatives with owners and operational evidence.
3. Obtain the applicable Vercel DPA and verify the exact Talli account/customer
   acceptance path for Supabase's incorporated Version 1 DPA; pin dated
   subprocessor schedules and complete human legal/privacy/security review,
   preserving acceptance/account evidence, artifacts and digests.
4. Obtain action-time confirmation, rotate Vercel's five database bindings to the
   exact Supabase project, and prove Preview/Production binding without revealing
   secrets.
5. Implement separate database and Storage-object backups with explicit retention,
   encryption, access, deletion, RPO and RTO.
6. Rehearse restore into an isolated destination and preserve timestamps, hashes,
   row/object reconciliation, independent reviewer identity and cleanup evidence.
7. Pin the approved Vercel and Supabase regions, plan IDs, deployment/database
   revisions, DPA versions, subprocessors, log windows and recovery evidence.
8. Keep the held legal migration and public production activation serialized behind
   their existing billing, legal and founder gates.

Until those steps are evidenced, the correct #196 state is:
`technical-hosted-facts-pinned-external-gates-remain-red`.

## Primary sources

### Vercel

- [Hobby plan](https://vercel.com/docs/plans/hobby)
- [Pro plan](https://vercel.com/docs/plans/pro-plan)
- [Pricing](https://vercel.com/pricing)
- [Terms of Service](https://vercel.com/legal/terms)
- [Runtime Logs](https://vercel.com/docs/logs/runtime)
- [Function region configuration](https://vercel.com/docs/functions/configuring-functions/region)
- [Regions](https://vercel.com/docs/regions)
- [Data Processing Addendum](https://vercel.com/legal/dpa)
- [Trust Center and subprocessor material](https://security.vercel.com/)

### Supabase

- [Pricing](https://supabase.com/pricing)
- [Database Backups](https://supabase.com/docs/guides/platform/backups)
- [Logging](https://supabase.com/docs/guides/monitoring-and-debugging/logs)
- [Log Drains](https://supabase.com/docs/guides/monitoring-and-debugging/log-drains)
- [Platform Audit Logs](https://supabase.com/docs/guides/security/platform-audit-logs)
- [Access Control](https://supabase.com/docs/guides/platform/access-control)
- [Regions](https://supabase.com/docs/guides/platform/regions)
- [Security and GDPR support](https://supabase.com/docs/guides/security)
- [Legal Hub](https://supabase.com/legal)
- [Terms of Service](https://supabase.com/terms)
- [Data Processing Addendum, Version 1 — August 1, 2026](https://supabase.com/legal/customer-resources/data-processing-addendum)
- [Current Subprocessor List landing page](https://supabase.com/legal/customer-resources/subprocessor-list)
- [Subprocessor List — Updated June 1, 2026](https://supabase.com/legal/subprocessor-list/June-1-2026.pdf)
- [Shared Responsibility Model](https://supabase.com/docs/guides/deployment/shared-responsibility-model)
- [Secure data and secret handling](https://supabase.com/docs/guides/database/secure-data)
