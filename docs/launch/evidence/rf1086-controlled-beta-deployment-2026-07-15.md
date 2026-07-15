# RF-1086 controlled-beta deployment evidence — 2026-07-15

Status: deployed fail-closed; production submission remains disabled

This record captures machine-observed deployment facts. It is not a legal,
security, authority, restore, support, or founder approval and must not be used
as a substitute for a `launch_signoffs` decision.

## Deployment

- Source commit: `9ee8032a1cd560b958d8e2a67c54e9c0093fcf3b`
- Vercel deployment: `dpl_37hV6azfdnx2Q2bmpmM3kK4w1N8o`
- Production aliases: `https://talli.no` and `https://www.talli.no`
- Vercel status after deployment: `Ready`
- HTTP probes after deployment: `/` returned 200 and `/login` returned 200.
- `TALLI_RF1086_PRODUCTION_ENABLED=false` is stored for Production and Preview.
- The exact production scope is stored for Production and Preview.
- The production Maskinporten client ID, key ID, and private PEM are configured
  as sensitive Vercel Production variables only. Preview has no production
  credential material.

## Hosted data boundary

- Supabase migration `20260715180000_controlled_production_beta` is applied.
- Local and remote migration histories match through `20260715180000`.
- `production_pilot_entitlements`, `filing_approval_snapshots`,
  `production_filing_submissions`, and `production_filing_events` exist with RLS
  enabled.
- All four production-beta tables contained zero rows immediately after the
  migration. No customer entitlement, approval, submission, or event was
  synthesized as part of deployment.
- The deployed PostgREST OpenAPI contract exposed all 28 required table/RPC
  paths.
- The production event journal RPC is executable only by `service_role`.
  Approval and begin RPCs remain intentionally available to `authenticated`,
  with their database-enforced owner, membership, entitlement, release-gate,
  signed AAL2, and fresh-MFA checks.

## Verification executed

- `npm run typecheck`: passed.
- `npm run build`: passed.
- RF-1086 controlled production, submission, security, filing release-gate, and
  backup/restore suites: 59 tests passed.
- Python RF-1086, submission, and billing suites: 25 tests passed.
- Hosted schema contract: ready, 28 required paths present.
- Supabase advisors: no `ERROR` findings. The three controlled-beta warnings are
  the intentionally authenticated security-definer RPCs described above.
- Supabase also reports leaked-password screening disabled. The project is on
  the Free plan, where that control is unavailable; email confirmation, secure
  password changes, and a 12-character minimum remain active.

## Preview runtime incident

- A production owner-session check found that preview generation failed because
  the deployed Node function attempted to start a project Python runtime that is
  not present in Vercel.
- The no-activity preview renderer and simulation adapter were moved in-process
  to TypeScript. Python is retained as an offline reference oracle only.
- Regression tests exercise both paths and require byte-for-byte XML parity and
  exact simulated request-plan parity. The production submission switch remains
  false; this remediation does not call an authority endpoint or broaden the
  supported filing profile.

## External state observed

- Digdir supplier terms were already signed on 2026-06-29.
- Production Maskinporten client `4a42d9fe-9759-4d4e-a07a-84ebc80a5a1b` was
  created for RF-1086 only.
- Active key ID `93fea8a9-4435-4fdc-84fc-775803714c53` is RS256/RSA, expires
  2027-07-15, and has public-key SHA-256 fingerprint
  `ecd338a4ecb5d087992884cccaae9035bed8fe30e8de4ac9fe71a2488c6e1ef3`.
- A portal-generated key that was rendered inline was discarded before save.
  The active key was generated locally, only its public half was registered,
  its private half was transmitted directly to the managed Vercel Production
  secret, and the temporary local files were securely removed.
- A non-delegated production token mint succeeded for exactly
  `skatteetaten:innrapporteringaksjonaerregisteroppgave` with a 119-second
  lifetime. No access token was persisted and no filing endpoint was called.

## Gates that remain deliberately closed

1. Register Talli's production Systembruker boundary and obtain a real pilot
   company's production delegation.
2. Record the exact pilot company/user/year entitlement only after that owner
   has joined Talli and the delegation evidence is available.
3. Complete and record the named `launch_legal_name_public_copy`,
   `legal_policy_pack`, `security_restore`, `support_rollback`,
   `rf1086_authority`, and `founder_production_go_live` approvals. The restore
   evidence must be no more than 30 days old.
4. Perform the delegated read-only pre-flight, keep the switch false through
   owner review, and set it true only for the named hand-held first filing.

Until every gate above is evidenced, Talli may generate and review the supported
RF-1086 preview, but it cannot send a production filing.
