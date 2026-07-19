# Hosted schema parity and atomic investment evidence

Status: passed for the invite-only beta database target
Date: 2026-07-15
Project: `oytdpbtzoibocshwunss` (`eu-west-1`, PostgreSQL 17)
Application: `https://talli.no`

No credentials, JWTs, API keys, document contents, or personal identifiers are
included in this record.

## Baseline diagnosis

The live PostgREST OpenAPI contract exposed the baseline workspace schema but none
of the paths introduced by repository migrations `0002+`. The project also had no
`supabase_migrations.schema_migrations` table. This explained both customer-visible
symptoms from the browser rehearsal:

- `record_share_purchase_fifo` was unavailable, so a supported purchase reached
  the server action and failed at the atomic RPC boundary;
- optional post-baseline table reads failed, so the aggregate workspace loader
  displayed `Tilkobling: Feil` despite healthy baseline reads and writes.

Pre-deploy counts were recorded without row contents:

| Object | Rows |
| --- | ---: |
| companies | 1 |
| documents | 1 |
| bank transactions | 3 |
| ledger entries | 2 |
| holding actions | 0 |
| investment positions | 0 |
| filing submissions | 0 |

## Migration rehearsal and application

Before the hosted change, the full repository chain applied to a fresh local
Supabase stack. Authenticated tenant isolation, private persistence, the owner
browser reload loop, static schema tests, and the corporate PostgreSQL runtime
rehearsal passed. The local advisor reported zero blocking security/error
findings.

The following versions were then applied in one hosted database transaction and
recorded in migration history:

1. `0001_authenticated_workspace`
2. `0002_fifo_investment_lots`
3. `0003_bank_rule_suggestions`
4. `0004_corporate_document_artifacts`
5. `0005_company_tax_feedback_persistence`
6. `20260714081443_explicit_data_api_grants`
7. `20260715084507_trusted_aal2_boundary`
8. `20260715120700_revoke_anonymous_mutation_rpcs`
9. `20260715143000_retention_safe_document_removal`

The first seven files were applied atomically because the hosted baseline had
been restored without migration history. Migration eight was added after the
hosted advisor revealed explicit legacy `anon` EXECUTE grants that were not
present on the fresh local project. Migration nine followed the retention-safe
document lifecycle rehearsal.

Post-deploy verification showed unchanged baseline row counts, all 20 required
Data API table/RPC paths, and all five critical RPCs. Anonymous execution is now
revoked explicitly for share purchase, share sale, and bank-suggestion mutations.

The final migration adds an owner-only, audited removal boundary for accidental,
unlinked uploads. It refuses documents referenced by holding actions, filing
feedback, immutable corporate artifacts, or ledger evidence. Storage SELECT is
revoked as soon as the row is marked removed, and Storage DELETE is permitted only
for that same owner and that database-approved object. The retained metadata records
who requested removal and why; a five-minute rollback RPC restores metadata if the
Storage API fails. The fresh local database rehearsal proved owner success,
reviewer/outsider denial, linked-evidence denial, signed-link denial after removal,
object deletion, and audit persistence.

## Signed-in browser proof

Safari signed in through the existing Google flow and loaded the production
workspace. `Tilkobling OK` replaced the prior false connection error. A synthetic
Test-Norge purchase was then posted for `LOGISK ØDE TIGER AS` (`310279617`):

| Persisted result | Count/value |
| --- | ---: |
| holding action | 1 |
| linked ledger entry | 1 |
| investment position | 1 |
| FIFO acquisition lot | 1 |
| shares | 100 |
| cost basis | NOK 50,000 |
| lot history | `complete` |

This is a beta-test record in the existing test workspace and is intentionally
retained as the reproducible holding workflow fixture.

## Hosted advisor reconciliation

The three anonymous `SECURITY DEFINER` warnings were removed. Remaining database
advisor findings are reviewed, intentional boundaries:

- `corporate_accounting_policies` has RLS and no customer policy because it is an
  operator-reviewed server fact consumed only inside validated RPCs;
- legacy `step_up_events` has RLS and no customer policy/grant because signed
  Supabase AAL2 claims replaced customer-authored trust state;
- the authenticated `SECURITY DEFINER` functions are the product's deliberately
  exposed mutation/RLS-helper boundary. Each mutation validates the authenticated
  subject, company ownership, payload invariants, period state, and idempotency;
  internal helpers remain non-executable by customers.

Supabase leaked-password checking could not be enabled because the project plan
does not include that paid feature. The free controls were tightened to a
12-character password minimum and reauthentication before password changes. A
Pro-plan decision remains an infrastructure/launch gate; no spend was committed.

Advisor references:

- [RLS enabled without policy](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)
- [Authenticated security-definer function](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)
- [Password security and leaked-password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)
