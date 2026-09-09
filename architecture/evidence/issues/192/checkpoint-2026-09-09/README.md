# Annual billing checkpoint — 9 September 2026

**Issue #192 remains open and incomplete.** Product revision
`8383672d10b465e7adafb4c45939bc1b630f4aa3` adds operator recovery of a recorded
agreement STOP, corrects checkout-worker settlement identity and lifecycle
declarations, hardens the Merchant Test runner, and updates vulnerable production
dependencies. Recovery preserves the original request, receipt, company, provider
and monetary facts. It requires current administrator access, an explicitly opened
billing support case and fresh MFA; it cannot create or execute an operation.

## Verified work

- Billing: **864 Python + 302 Node tests passed**.
- Real local PostgreSQL: **699 Python tests passed**, followed by the corrected
  **1 Node migration lifecycle test**, with zero skips. The Node fixture now uses
  unique keys for each run. Its first collision and the rerun are retained in the
  [database log](checks/database.log). Missing fixture adapters and synthetic
  host/database clock skew were corrected without relaxing production authority.
- Web/backend builds, typecheck and credential checks passed. Both production
  dependency audits report zero vulnerabilities after the Next, PostCSS and sharp
  updates.
- [Desktop/mobile browser verification](browser/REPORT.md): 43 assertions through
  shipped UI, server action, generated transport and the actual FastAPI route.
  Authentication, persistence and provider fixtures were synthetic. This does not
  prove the production dashboard/session/database integration.
- Independent scoped web, backend and worker reviews found no actionable issues.
  These do not constitute the final whole-issue release review.

See [verification.json](verification.json) for counts, source attribution and
limits. The broad boundary run preceded the final runner-only extension; the
later billing run includes all 60 final runner tests. Browser and webhook source
hashes match the committed product revision. Real provider runs retain their
original working-tree `-dirty` attribution.

## Actual Vipps Merchant Test

All provider calls used `https://apitest.vipps.no`, existing test unit **535717**
and the registered synthetic MT user. No production payment or activation occurred.
The standalone runner stores synthetic provider intent outside the business
ledger; these observations do not grant paid entitlement or establish filing
readiness.

| Scenario | Observed result |
| --- | --- |
| Initial agreement and NOK 1,490 capture | Confirmed on `agr_Un4JzLG`. |
| Partial refund | NOK 372.50 confirmed; exact refund replay left the amount unchanged. |
| Remaining refund | NOK 1,117.50 confirmed; initial charge is fully refunded. |
| Recurring charge and replay | One intended charge scheduled for 10 September; replay returned the same charge. Capture is still pending. |
| Separate future charge cancellation | Confirmed cancelled with zero captured. |
| Independent single full refund | NOK 1,490 confirmed on `agr_Xwpy7fP`; exact refund replay left the amount unchanged. |
| Agreement stop and recovery | `agr_Xwpy7fP` stopped; ordinary retry used only a provider read. |
| Signed webhooks | Eight actual events durably received; nine exact replays preserved receipt ID, time and digest; three altered payloads rejected with HTTP 401. |

The [provider readback](provider/issue-192-provider-readback-20260909.json) records
the final agreement and charge states. [Webhook evidence](webhooks/REPORT.md)
separately proves the shipped HMAC route and PostgreSQL technical inbox through a
free temporary HTTPS tunnel. Webhooks are delivery receipts, not financial
settlement authority. That registration, tunnel, server and isolated database
were removed after export; [cleanup](webhooks/cleanup.json) verifies this.

### Agreement replay incident and correction

Deliberately resending checkout creation with the same stored key and intent
created another pending agreement, `agr_5YSKYz2`, in MT. Raw provider agreement
creation idempotency therefore **failed this test**. Subsequent unbound searches
correctly refused the ambiguous result; separate HTTP 429 observations were also
retained. No second agreement was approved and no second charge was created.
An attempted STOP of that pending draft returned HTTP 400. The draft subsequently
expired, confirmed by both its authenticated expiry event and provider readback.

Normal billing checkout and the observation worker already reconcile the original
recorded agreement instead of resending creation. The standalone runner now
rejects checkout `repeat-execute` before any state write or network call. It binds
reconciliation to one consistent previously observed agreement ID, including
after an unknown result, while keeping the stored intent and key unchanged.
Conflicting IDs remain unavailable. The original payment then reconciled
successfully without another agreement-list request or mutation. Regression tests
model a provider that does not deduplicate creation; no fixture guarantee is
presented as real-provider proof.

## Work still required

The immutable customer-ready gate on `8383672d` passed credential scanning and
typecheck, then **failed the same four unapproved frozen-scope deletions**. Its
[transcript](../../../customer-ready-gates/8383672d10b465e7adafb4c45939bc1b630f4aa3.log)
is a failure record, not an 11/11 pass. The prepared
[exact retirement patch](pending-legacy-retirement.patch) is evidence only and has
**not** been applied; the active checker, immutable baseline and ADR are unchanged.
The [retirement proposal](../legacy-retirement-amendment-proposal.md) and
[source-order proposal](../source-order-amendment-proposal.md) still await the
explicit decision required by ADR 0013.

Authoritative filing readiness, incident/submission facts, next-year admission,
ordinary paid entitlement and automatic renewal/refund integration remain
unavailable under the current source order. They cannot be replaced with fixture
facts. Full customer/operator acceptance, two linked immutable complete gates,
protected-main Release/Preview integration and post-merge evidence remain due.
No successor capability has been claimed and `release/production` is unchanged.

The intended recurring charge on `agr_Un4JzLG` is due **10 September 2026**.
Reconcile that original run after actual MT processing, refund the captured
recurring charge with its existing `full-refund` stage, then stop the original
agreement. Its state and backend-only test configuration are retained privately.
No automatic continuation was established by this checkpoint. The public callback
is currently removed; recreate a test callback if further delivery evidence is
needed. Never edit state to fabricate capture or create a new run to recover it.

Official references: [Recurring guide](https://developer.vippsmobilepay.com/docs/APIs/recurring-api/recurring-api-guide/),
[Recurring API](https://developer.vippsmobilepay.com/api/recurring),
[MT environment](https://developer.vippsmobilepay.com/docs/knowledge-base/test-environment/).

The [artifact hashes](artifact-sha256.json) cover the sanitized evidence. API keys,
tokens, raw webhook signatures, the synthetic user's phone/NIN, and private
runtime configuration are excluded from this directory.

Copied build/typecheck logs have only terminal carriage returns, trailing spaces
and trailing blank lines normalized. Empty context lines in the pending patch
were normalized for repository whitespace checks. Applying the original and
normalized patches to isolated indexes at `8383672d` produced the same Git tree;
neither was applied to the product checkout. The original proposal patch SHA-256
is `38db4d7e1d9f85a868cd66d25c37edf71f3c97695d98b3c54237705975988014`.
