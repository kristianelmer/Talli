# Founder Pricing and Filing Billing Gate

Status: product baseline

Talli should undercut broad accounting systems, but not by charging before value is deliverable. The launch pricing model separates a cheap subscription from a production filing package.

## Pricing

Founder cohort:

- First 100 companies.
- `29 kr` per month.
- `299 kr` per successful production filing package.

Standard launch pricing:

- `49 kr` per month.
- `499 kr` per successful production filing package.

Rationale:

- Low monthly price makes Talli easy to try for low-activity holding companies.
- Filing package captures value only when Talli can move the user through direct filing.
- Founder pricing compensates early users for product risk and lower trust.

## Billing Gate

Production filing can start only when:

- Subscription is active.
- Filing readiness has passed.
- Case is supported.
- Filing package is paid.

Charge policy:

- Do not charge filing package while readiness is blocked.
- Do not charge filing package when the case is outside support scope.
- Allow filing-package charge only after readiness passes.
- If Talli accepts a supported case and production filing fails because of Talli's filing logic or integration, mark the account refund-eligible.

Implementation anchor: `holding_core.billing`.
