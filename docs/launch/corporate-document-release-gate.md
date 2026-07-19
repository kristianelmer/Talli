# Corporate Document Release Gate

Status: blocked — external reviews and deployed-environment evidence are pending  
Owner: release manager  
Last updated: 2026-07-14  
Feature flag: `TALLI_CORPORATE_DOCUMENTS_ENABLED=false`

The corporate-document workflow must remain disabled in every public environment until every row below has a named reviewer, review date, immutable evidence reference, and explicit approval. Local automated tests do not substitute for Norwegian legal or accounting review.

| Gate | Required reviewer and evidence | Current status | Release effect |
| --- | --- | --- | --- |
| Four Norwegian templates | Named Norwegian corporate-law reviewer; reviewed PDFs for dividend board proposal, dividend general-meeting minutes, annual board minutes, and annual general-meeting minutes; template version and PDF SHA-256 values | Pending | Blocks feature enablement |
| Dividend accounting policy | Named Norwegian accounting professional; approved declaration debit, dividend-payable, and bank accounts; review date and evidence reference recorded in one enabled immutable `corporate_accounting_policies` version | Pending | Blocks owner-dividend finalization and payment |
| PDF golden and visual approval | Named product/legal reviewers; deterministic rerender hashes, `pdfinfo`, extracted text, and screenshots for every page of all four templates | Pending | Blocks feature enablement |
| Deployed RLS and private storage | Named security reviewer; authenticated owner/member/cross-tenant tests against the target Supabase project; proof that unsigned and signed objects are private and immutable | Pending | Blocks feature enablement |
| Backup and restore rehearsal | Named operator; isolated restore target, manifest and object-verification output, relationship checks, and restore date no older than 30 days | Pending | Blocks production launch and cancellation/deletion progression |
| Corporate public copy | Named legal/product reviewer; approval of review, signing, owner-attestation, finalization, payment, and limitation copy | Pending | Blocks feature enablement |

## Automated evidence available locally

The implementation provides deterministic PDF generation, canonical decision and content hashes, private content-addressed storage keys, immutable lifecycle rows, fresh owner MFA gates, owner-only preview, policy-bound database finalization/payment, and archive/restore integrity checks. The local Task 12 rehearsal records exact command output and artifact hashes; named external reviews and deployed-environment evidence remain required.

The Task 12 local rehearsal completed on 2026-07-14 for commit
`aa3afaf5bd3bd7e100e108b74e2a8eb03354fd4c`. Exact commands, environment
versions, PDF/font/screenshot hashes, fresh PostgreSQL attack-path coverage, and
the deployed-Supabase skip are recorded in
`docs/launch/evidence/corporate-document-local-rehearsal.md`. Local evidence
does not change any pending row above.

## Enablement procedure

1. Complete every gate above without changing a pending row to approved on assumption.
2. Record the reviewed template version and accounting-policy version in the release evidence.
3. Run the complete production rehearsal from `docs/launch/production-launch-rehearsal.md` against the target release commit.
4. Confirm the latest deployed RLS/storage and restore evidence is attached and current.
5. Change `TALLI_CORPORATE_DOCUMENTS_ENABLED` only in the approved target environment, then run a smoke test with a synthetic holding company.
6. Roll back the flag immediately if hashes, private-object access, signer requirements, accounting policy, or archive evidence differ from the approved baseline.

Until then, the application must describe these documents as disabled or under review. It must never describe an owner-attested uploaded copy as a cryptographically verified signature.
