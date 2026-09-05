# Annual billing page browser checkpoint

The desktop (1440 px) and phone (390 px) screenshots show the actual Next.js
owner page with synthetic local Company Access, session and annual billing API
responses. These are UI fixtures, not merchant-test, production, database or
export-download evidence. The fixture offers and stored terms are synthetic.

Manual Playwright checks covered paid, pending, refunded, empty, unavailable and
fresh-MFA recovery states. The phone had no horizontal overflow and the renewal
cancellation button was 44 px high. A failed first cancellation response retained
the exact company, purchase and operation key on retry. A response lost after
saving cancellation showed the persisted cancellation on the subsequent read,
retained paid-access dates and did not display a second cancellation action.

The first MFA fixture response omitted two required problem-document fields and
was correctly rejected by the generated client. Repeating with the actual error
shape showed the MFA recovery link. A transport regression also covers malformed
and valid error responses. No billing/provider policy was weakened.

The page exposes annual history and local cancellation only. Legacy acquisition
and entitlement retirement, annual checkout/refund/worker integration, real MT,
source-owned readiness and the complete #192 release gates remain outstanding.
