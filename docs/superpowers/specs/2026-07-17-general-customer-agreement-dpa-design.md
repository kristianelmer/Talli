# General Customer Agreement and DPA Design

Status: approved in conversation by Kristian Elmer on 2026-07-17

Decision owner: Kristian Elmer

Current supplier: ELMER WELFIS, org.nr. 930 835 978

## Objective

Give beta and generally available customers the same contractual onboarding:
an authorized representative creates a company workspace and explicitly accepts
one durable set of Talli Business Terms and the incorporated Data Processing
Agreement (DPA). Beta remains a plan and capability state, not a different legal
experience.

## Decisions

- The customer agreement is named **Talli Business Terms** (`Brukervilkår for
  bedriftskunder`) in the product.
- The Business Terms and DPA are separate, versioned documents accepted in one
  company-onboarding action.
- Account signup does not constitute company acceptance. Acceptance occurs when
  an authenticated user creates a workspace for a Brønnøysund-verified company.
- The user must affirm that they are authorized to bind the named company.
- The Privacy Notice is disclosed but not presented as a contract the customer
  must accept.
- The beta customer uses the same acceptance control as a later paid customer.
  The persisted service plan, price, entitlements, and production gates describe
  what is currently available.
- Passive or continued use, footer links, or a pre-selected checkbox do not
  count as acceptance. Every material new agreement version requires explicit
  re-acceptance by an authorized representative and a new immutable acceptance
  record before it binds the customer.
- For existing companies, the owner layout compares tenant-readable evidence
  with the pinned current versions and digests and replaces owner-route content
  with an explicit re-acceptance control until an accepted owner appends exact
  current evidence. This is a service-access gate, not a filing, billing, or
  entitlement switch.
- DocuSign, BankID signing, negotiated order forms, and enterprise amendments
  remain optional later paths, not dependencies of self-service onboarding.

## Considered approaches

### 1. Separate signed beta agreement

This gives strong bespoke evidence but creates a temporary onboarding path and a
manual signing dependency. It also makes the beta feel unlike the intended live
service. Rejected as the default.

### 2. Accept terms at account signup

This is common for consumer services, but a Talli account may exist before the
user selects a company and proves which legal entity they represent. It would
also force personal users to accept a company DPA without an identified
controller. Rejected.

### 3. Accept versioned Business Terms and DPA at company creation

Selected. The Brønnøysund lookup identifies the customer, the authenticated user
affirms authority, and Talli records the exact documents accepted. This produces
one reusable beta-to-live experience.

## Contract documents

### Business Terms

The public Business Terms are the general customer agreement. They identify
ELMER WELFIS as the current supplier and cover:

- the holding-first supported scope and unsupported cases;
- account and company authority;
- customer review and filing responsibility;
- the distinction between preparation, local approval, transport receipt, and
  final authority acceptance;
- plan, price, beta/early-access functionality, and paid-service activation;
- the reviewed filing-package refund boundary while live billing remains gated;
- acceptable use, confidentiality, customer data rights, service feedback,
  support, suspension, termination, export, liability, governing law, and term
  changes;
- incorporation and priority of the DPA for processor activity.

The terms do not imply that beta is a separate contract or that production
filing is enabled. Every material future agreement version requires explicit
authorized re-acceptance with immutable evidence; continued use is never
acceptance evidence.

### DPA

The public DPA identifies the customer as controller for its company,
shareholder, accounting-document, and filing data, and ELMER WELFIS/Talli as
processor for providing the service on documented instructions. It covers the
mandatory Article 28 subjects:

- subject matter, nature, purpose, and duration;
- data-subject and personal-data categories;
- documented instructions and unlawful-instruction notice;
- confidentiality and technical/organizational security measures;
- subprocessor authorization and mandatory advance notice before a change,
  without a practicality exception;
- international-transfer safeguards;
- data-subject, breach, DPIA, regulator, and audit assistance;
- return, deletion, retention exceptions, and termination.

The DPA distinguishes Talli's narrow independent-controller activity for account
administration, security, legal compliance, and its own business records. The
subprocessor and security annexes state only facts verified for the deployed
service; unverified locations, certifications, and transfer bases are not
published as facts.

### Versioned document registry

One server-only module is the canonical registry for contract metadata:

```ts
type ContractDocument = {
  kind: "business_terms" | "dpa";
  version: string;
  effectiveDate: string;
  path: "/vilkar" | "/databehandleravtale";
  contentSha256: string;
};
```

The expected SHA-256 digest is pinned beside each document version. At module
initialization, Talli serializes the exact public copy, hashes it, and fails if
the result differs from that version's pinned digest. Tests and builds therefore
fail when content changes without an intentional version and digest update.
Historical accepted metadata is immutable; publishing a later version
does not rewrite prior acceptance records. Version `2026-07-17` remains
unchanged during this pre-release correction only because no customer
acceptance for that version has been released or recorded. After any customer
acceptance exists, changing canonical content requires a new version and new
explicit acceptance.

## Acceptance experience

The existing company-creation panel continues to start with a nine-digit
organization number. Before submission it shows one required, unchecked
control:

> Jeg bekrefter at jeg har fullmakt til å inngå avtale på vegne av selskapet,
> og godtar Talli Brukervilkår for bedriftskunder og Databehandleravtalen.

`Brukervilkår for bedriftskunder` and `Databehandleravtalen` link to their
current public, versioned pages and open without losing form state. The form
submits the current version and pinned digest for both documents. The submit
button remains the existing company-creation action. Before Brønnøysund lookup
or service-role work, server validation rejects a missing or unexpected
checkbox value and any version or digest mismatch; client-only validation is
not trusted.

After the submitted versions and digests match the rendered registry, the
server uses only the trusted current registry metadata in the 19-key RPC
payload. Brønnøysund then resolves the organization number and the server binds
acceptance to the resolved legal name and organization number. If validation,
lookup, supported-AS check, company insert, owner membership, or acceptance
insert fails, no partial company is created.

The workspace lists the active plan and capabilities independently of the legal
documents. During beta this can remain `Free beta`, preparation/comparison
enabled, and direct production filing disabled. General availability changes
those service records, not the acceptance UI.

## Persistence and atomicity

Add an append-only `customer_agreement_acceptances` table with:

- generated acceptance ID;
- company ID and accepting user ID;
- customer legal name and organization number captured at acceptance;
- Business Terms version, effective date, path, and SHA-256 digest;
- DPA version, effective date, path, and SHA-256 digest;
- authority-statement version;
- acceptance method (`in_app_clickwrap`);
- acceptance timestamp;
- creation timestamp.

Rows cannot be updated or deleted through the customer API. A company owner may
read the company's acceptance record. Support access follows the existing
audited support boundary. The table does not store passwords, tokens, document
bodies, or broad browser fingerprints.

Company creation moves behind one service-role-only security-definer database
function called exclusively from the authenticated Server Action. Browser clients
cannot execute the function. The Server Action supplies the user ID only after
`getUser()` succeeds, and the function:

1. verifies the service-role caller and supplied authenticated user ID;
2. accepts only server-supplied, Brønnøysund-normalized company identity;
3. creates the company;
4. creates the accepted owner membership;
5. writes the immutable agreement acceptance;
6. writes the workspace-created audit event;
7. returns the company ID;
8. rolls back the whole transaction on any failure.

The function validates required versions, digests, paths, authority statement,
and acceptance method against explicit arguments supplied by trusted server
code. Its execute privilege is revoked from `public`, `anon`, and
`authenticated`; the acceptance table grants the service role only the minimum
read access needed for evidence. It does not grant production-filing entitlement
and does not bypass any existing launch or authority gate.

Existing company workspaces are not silently backfilled. No historical
acceptance is fabricated. A later migration flow may collect current acceptance
for a real pre-existing customer before named-company processing continues.
Synthetic development fixtures remain test-only and do not represent customer
acceptance.

## Failure behavior

- Missing authority/acceptance: remain on the workspace with a clear Norwegian
  error and create nothing.
- Stale form version: reject safely and ask the user to review the current
  documents; do not silently substitute a new version.
- Brønnøysund failure or unsupported entity: retain the current fail-closed
  behavior and create nothing.
- Database failure: roll back company, membership, acceptance, and audit event.
- Later material agreement versions: notify customers and require explicit
  authorized re-acceptance with new immutable evidence before the version binds
  the customer; continued use is not acceptance evidence.

## Tests

The implementation uses test-driven development and proves:

- the registry exposes two current, versioned documents with stable digests;
- the terms and DPA public routes render the current versions and operator;
- the company form contains an unchecked required authority/acceptance control
  with both document links;
- the server rejects missing, false, or stale acceptance;
- the migration creates an immutable, tenant-readable acceptance table;
- the atomic creation function writes company, owner membership, acceptance,
  and audit data together and grants no filing entitlement;
- legal-policy tests cover the general beta-to-live model and Article 28
  substance;
- typecheck, build, relevant Node tests, and the local Supabase database suite
  pass before completion.

## Security and privacy

- Acceptance is company-scoped and tied to an authenticated user.
- Brønnøysund remains authoritative for customer identity at creation.
- The acceptance table is append-only and protected by RLS and explicit grants.
- Contract records contain the minimum evidence needed to identify the parties,
  documents, assent, and time.
- No contract acceptance enables billing, production credentials, authority
  transport, filing entitlement, or customer-data support access.
- The named-company beta entry gate still separately requires approved current
  hosted tenant-isolation, private-storage, and restore evidence.

## Out of scope

- External legal approval or a claim that the documents are legally approved.
- Incorporating or migrating the supplier to Talli AS.
- DocuSign, BankID, or another paid signing provider.
- Negotiated enterprise terms and order forms.
- Paid-plan activation or pricing decisions.
- Enabling production filing.
- Fabricating acceptance for existing workspaces.

## Release boundary

This feature changes the evidence behind the legal beta-entry condition from a
manual signature expectation to a binding, explicit, versioned electronic
acceptance. It does not by itself clear that condition for a named customer: the
final Business Terms, DPA, subprocessor facts, security appendix, and liability
wording still require founder/legal/security approval, and the separate hosted
isolation/storage/restore condition must also pass.
