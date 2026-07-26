# Onboarding Agreement and Error Handling Design

## Goal

Make company onboarding submit the agreement evidence required by the server action
and keep onboarding failures visible instead of redirecting a returning user into an
existing workspace.

## Scope

- Render the authority and agreement acceptance control plus current agreement
  version and hash fields in the company lookup form.
- Preserve and show the server-action error on `/onboarding` before applying the
  returning-user redirect.
- Add regression coverage for both behaviours.

## Non-goals

- Change Brønnøysund lookup behaviour.
- Change company membership, workspace selection, or tenant isolation.
- Add a second company-management flow.

## Behaviour

The form must send `agreementAccepted`, `businessTermsVersion`,
`businessTermsSha256`, `dpaVersion`, and `dpaSha256` with the organisation number.
If onboarding fails, the user remains on `/onboarding` and sees the returned error,
even if they already have a completed workspace. A successful submission retains the
existing redirect behaviour.

## Verification

Tests assert that the rendered form contains every required agreement field and that
the onboarding page renders an error before any completed-workspace redirect.
