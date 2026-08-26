from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPAND = ROOT / "supabase/migrations/20260826100000_company_access_onboarding.sql"
CONTRACT = ROOT / "supabase/contract-migrations/20260826101000_company_access_onboarding_contract.sql"


def migration(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_expand_migration_exposes_replay_safe_rls_bound_atomic_commands() -> None:
    sql = migration(EXPAND)

    assert "company_access_onboard_company" in sql
    assert "company_access_reaccept_agreement" in sql
    assert "'onboard_company'" in sql
    assert "'reaccept_agreement'" in sql
    assert "owner to company_access_executor" in sql
    assert "to company_access_executor" in sql
    assert "nobypassrls" in sql
    assert "talli_company_access_backend" in sql
    assert "with inherit false, set true" in sql
    assert "public.company_access_auth_uid_v1()" in sql
    assert "public.company_access_current_identity_v1()" in sql
    assert "grant execute on function public.company_access_onboard_company" in sql
    assert "grant execute on function public.company_access_reaccept_agreement" in sql
    assert "normalize the predecessor overlap acl" in sql
    assert "public.company_access_create_invitation" in sql
    assert "public.company_access_request_cancellation" in sql
    assert "talli.verified_actor_id" in sql
    assert "talli.verified_actor_claims" in sql
    assert "revoke all on function public.company_access_onboard_company" in sql
    assert "revoke all on function public.company_access_reaccept_agreement" in sql
    assert "from public, anon" in sql
    assert "grant execute on function public.company_access_onboard_company" in sql
    assert "to service_role" not in sql
    assert "auth.role()" not in sql

    onboard_acl = sql[sql.rindex(
        "revoke all on function public.company_access_onboard_company"
    ):]
    assert "to authenticated" not in onboard_acl
    assert "to service_role" not in onboard_acl

    onboard = sql.index("create or replace function public.company_access_onboard_company")
    reaccept = sql.index("create or replace function public.company_access_reaccept_agreement")
    onboard_sql = sql[onboard:reaccept]
    reaccept_sql = sql[reaccept:]
    assert onboard_sql.index("unsupported_entity_type") < onboard_sql.index("insert into public.companies")
    for table in (
        "public.companies",
        "public.company_memberships",
        "public.customer_agreement_acceptances",
        "public.audit_events",
        "public.company_access_command_receipts",
    ):
        assert f"insert into {table}" in onboard_sql
    assert "pg_advisory_xact_lock" in onboard_sql
    assert "replayed" in onboard_sql
    assert "insert into public.customer_agreement_acceptances" in reaccept_sql
    assert "accepted_owner_membership_required" in reaccept_sql
    assert "pg_advisory_xact_lock" in reaccept_sql
    assert "replayed" in reaccept_sql


def test_expand_keeps_legacy_rpcs_for_deploy_order_overlap() -> None:
    sql = migration(EXPAND)

    assert "drop function public.create_company_workspace_with_acceptance" not in sql
    assert "drop function public.append_company_agreement_acceptance" not in sql


def test_contract_artifact_closes_browser_authority_and_removes_legacy_surface() -> None:
    sql = migration(CONTRACT)

    assert "contract release artifact" in sql
    assert sql.startswith("-- contract release artifact")
    assert "\nbegin;\n" in sql
    assert sql.rstrip().endswith("commit;")
    assert "company_access_contract_step_up_events_not_empty" in sql
    assert "create_company_workspace_with_acceptance" in sql
    assert "append_company_agreement_acceptance" in sql
    assert "revoke all on function" in sql
    assert "drop function" in sql
    assert "company_access_onboard_company" in sql
    assert "company_access_reaccept_agreement" in sql
    assert "from public, anon, authenticated, service_role" in sql
    assert "talli.verified_actor_id" in sql
    assert "auth.uid()" in sql  # future archive and audit authorization seams
    assert "company_access_policy.authenticated_can_append_audit_v1" in sql
    assert "public.company_access_authenticated_can_append_audit_v1" not in sql
    assert "security definer" in sql
    assert (
        'create policy "company members can create audit events for themselves"'
        in sql
    )
    assert (
        "company_access_policy.authenticated_can_append_audit_v1(company_id, actor_id)"
        in sql
    )
    assert (
        "grant execute on function "
        "company_access_policy.authenticated_can_append_audit_v1(uuid, uuid)\n"
        "  to authenticated"
        in sql
    )
    assert "public.company_access_auth_uid_v1()," in sql
    assert "public.company_access_auth_jwt_v1()," in sql
    assert "public.company_access_is_accepted_owner_v1(uuid)" in sql
    assert "drop table if exists public.step_up_events" in sql
    assert "revoke all on table" in sql
