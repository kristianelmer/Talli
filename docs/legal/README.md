# Legal and Operational Policy Drafts

Status: draft pack for #72  
Last updated: 2026-06-24

Files:

- `terms-of-service-draft.md`
- `privacy-policy-draft.md`
- `dpa-draft.md`
- `retention-delete-export-policy-draft.md`
- `incident-response-policy-draft.md`

These drafts convert product decisions into reviewable policy text. They are not
legal signoff. Issue #72 should remain open until founder/legal/security review
records approval, dates, and any required changes.

## Founder decisions recorded (2026-06-24, Kristian Elmer)

The following open factual items were resolved by the founder and written into the
drafts above:

1. Controller/operator — Kristian Elmer (natural person), pre-incorporation;
   migrate to the Talli AS name + org number once registered.
2. Processors — Supabase (EU), Vercel, Vipps MobilePay (payment), Resend (email),
   Norwegian authority systems.
3. Retention floor — minimum 5 years for primary accounting material
   (bokføringsloven § 13).
4. Data transfer — EEA residency; US-incorporated suppliers (Vercel, Resend)
   covered by SCCs/DPF.
5. Breach notification — Datatilsynet within 72 hours (GDPR art. 33); high-risk
   user notice without undue delay (art. 34).

Still required before the `legal_policy_pack` signoff can be recorded as approved:

- Legal reviewer approves liability/jurisdiction, controller/processor role, and
  final privacy/DPA wording.
- Security reviewer confirms technical measures and support/operator access model.
- Founder approves customer-facing deletion/return obligations and refund wording.
- On incorporation, replace the pre-incorporation operator with the AS entity.

## Founder self-attestation (2026-06-24, Kristian Elmer)

For a **private/limited pre-launch only**, the founder has reviewed and approved
this policy pack as the operative drafts and elected to record the
`legal_policy_pack` signoff with **external legal review deferred**. This
attestation is scoped to limited early access and does **not** cover a broad
public launch.

Deferred follow-ups that must be completed before broad public launch:

- Independent legal review of liability/jurisdiction and controller/processor role.
- Security reviewer confirmation of production technical measures and
  support/operator access model.
- Entity migration to the Talli AS on incorporation.

Machine-checkable signoff gate:

- Implementation: `app/lib/launch-signoff.ts`
- Test: `npm run test:launch-signoff`
- Required key for this issue: `legal_policy_pack`
- Closure rule: terms, privacy policy, DPA, retention/delete/export policy, and
  incident response policy must be approved with reviewer, review date, evidence
  link, and decision. Draft text alone is not legal approval.
