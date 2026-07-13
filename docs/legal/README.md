# Legal and Operational Policy Drafts

Status: draft pack for #72  
Last updated: 2026-07-13

Files:

- `terms-of-service-draft.md`
- `privacy-policy-draft.md`
- `dpa-draft.md`
- `retention-delete-export-policy-draft.md`
- `incident-response-policy-draft.md`
- `corporate-document-drafts.md` (implementation boundary and source register;
  separate template-wording approval required)

These drafts convert product decisions into reviewable policy text. They are not
legal signoff. Issue #72 should remain open until founder/legal/security review
records approval, dates, and any required changes.

Machine-checkable signoff gate:

- Implementation: `app/lib/launch-signoff.ts`
- Test: `npm run test:launch-signoff`
- Required key for this issue: `legal_policy_pack`
- Closure rule: terms, privacy policy, DPA, retention/delete/export policy, and
  incident response policy must be approved with reviewer, review date, evidence
  link, and decision. Draft text alone is not legal approval.
