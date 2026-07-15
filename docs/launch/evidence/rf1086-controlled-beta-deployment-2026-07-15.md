# RF-1086 controlled-beta deployment evidence — 2026-07-15

Status: deployed fail-closed; production submission remains disabled

This record captures machine-observed deployment facts. It is not a legal,
security, authority, restore, support, or founder approval and must not be used
as a substitute for a `launch_signoffs` decision.

## Deployment

- Source commit: `dd3336cccaf76dee312f9dc75fb084eff29c2f85`
- Vercel deployment: `dpl_68B9trX4MP8vw4B88XuTLNVU6pz2`
- Production aliases: `https://talli.no` and `https://www.talli.no`
- Vercel status after deployment: `Ready`
- HTTP probes after deployment: `/` returned 200 and `/login` returned 200.
- `TALLI_RF1086_PRODUCTION_ENABLED=false` is stored for Production and Preview.
- The exact production scope is stored for Production and Preview.
- Production Maskinporten client ID, key ID, and private key are not configured.

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

## External state observed

- Digdir supplier terms were already signed on 2026-06-29.
- The production integration inventory was empty.
- Production self-service is reachable but requires a fresh Ansattporten/BankID
  login before a production client can be created.

## Gates that remain deliberately closed

1. Create a production-only Maskinporten client and key, then obtain the exact
   Skatteetaten production scope grant.
2. Obtain a real pilot company's production Systembruker/delegation and record
   an exact company/user/year entitlement.
3. Complete and record the named `launch_legal_name_public_copy`,
   `legal_policy_pack`, `security_restore`, `support_rollback`,
   `rf1086_authority`, and `founder_production_go_live` approvals. The restore
   evidence must be no more than 30 days old.
4. Configure the three managed production credential secrets only after the
   client and scope are verified.
5. Redeploy with the switch still false, perform a read-only pre-flight, and set
   the switch to true only for the named hand-held first filing.

Until every gate above is evidenced, Talli may generate and review the supported
RF-1086 preview, but it cannot send a production filing.
