# Incident Response Policy Draft

Status: draft for founder/security/legal review  
Last updated: 2026-06-24  
Blocks: #72 remains open until human/legal signoff

## Incident Categories

- Unauthorized access to company workspace or document.
- Cross-tenant data exposure.
- Lost or corrupted accounting/filing data.
- Compromised production secret or authority credential.
- Failed or duplicate authority submission.
- Payment/refund processing error.
- Availability issue close to statutory deadline.

## Response Flow

1. Detect and record incident.
2. Assign incident owner and severity.
3. Contain access, credential, deployment, or data-flow risk.
4. Preserve logs, audit events, affected ids, and timeline.
5. Assess affected customers, companies, documents, filings, and authority references.
6. Notify affected customers/users without undue delay where a personal-data breach
   is likely to result in high risk to their rights and freedoms (GDPR art. 34).
7. Notify Datatilsynet (Norwegian DPA) within 72 hours of becoming aware of a
   personal-data breach, unless it is unlikely to result in risk to individuals
   (GDPR art. 33); record the assessment and reasoning in either case.
8. Remediate root cause.
9. Run postmortem and add regression test or operational guard.

## Required Evidence

- incident id;
- reporter/detection source;
- severity;
- affected company ids;
- affected data classes;
- first detected time;
- containment time;
- customer notification decision;
- authority/regulator notification decision;
- root cause;
- corrective action;
- owner and due date.

## Filing-Specific Incidents

For direct filing incidents, preserve:

- filing preview id;
- payload hash;
- idempotency keys;
- authority call log;
- feedback/receipt ids;
- user confirmations;
- billing/refund state.

Duplicate or uncertain submissions must not be retried under changed payloads with
old idempotency keys.

## Required Human Review Before Publication

- [ ] Founder names incident roles.
- [ ] Security reviewer approves severity model and evidence checklist.
- [x] Notification thresholds/timing defined — Datatilsynet within 72h (GDPR art. 33);
  high-risk user notice without undue delay (art. 34). Legal to confirm wording.
- [ ] Support owner approves customer-message templates.
