"""Inventory assertions inside one already-owned independent identity context.

Creates no resource and never mutates SOURCE. Tokens and target handles stay
inside the caller's restored_identity lifetime; only a finite report escapes.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import base64
import json

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict

from rf1086_identity_restore import RecoveredIdentity, verify_target_session
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresCompanyTestRetentionSessionFactory
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId


@dataclass(frozen=True, slots=True)
class CompanyTestInventoryRecoveryReport:
    record_count: int
    records_sha256: str
    target_observed_at: str
    source_artifact_sha256: str
    original_recorded_actors_preserved: bool
    current_membership_roles_verified: bool
    outsider_unaccepted_banned_and_revoked_denied: bool
    revoked_and_soft_deleted_sessions_denied: bool
    authorized_successor_recovered_inventory: bool
    stateless_owner_session_denied: bool
    physical_auth_user_erasure: str


@contextmanager
def _target_connection(recovery: RecoveredIdentity):
    # Fixed live PID/container proof before EVERY synthetic target mutation.
    verify_target_session(recovery.database_url, recovery.database_container, recovery.bootstrap)
    with psycopg.connect(recovery.database_url) as connection:
        yield connection


async def verify_company_test_inventory_actor_recovery(
    recovery: RecoveredIdentity, company_id: CompanyId,
    expected: rf.Rf1086CompanyTestRetentionSnapshot, source_artifact_sha256: str,
    *, source_reader_url: str, anon_key: str, owner_token: str, outsider_token: str,
    stateless_owner_token: str,
) -> CompanyTestInventoryRecoveryReport:
    """Fresh canonical Auth for every read; recorded_by is never permission."""
    source = rf.serialize_rf1086_company_test_retention(expected).encode('utf-8')
    if (expected.company_id != company_id or expected.coverage != 'complete'
            or sha256(source).hexdigest() != source_artifact_sha256
            or conninfo_to_dict(source_reader_url).get('user') != 'talli_ledger_backend'
            or any(recovery.proof.get(key) is not True for key in (
                'independentClusterRestored', 'independentAuthRestored', 'authHttpTargetBindingVerified',
                'roleAttributesAndMembershipsRestored', 'ownershipGrantsAndRlsRestored', 'authRowsRestoredExactly'))):
        raise ValueError('Inventory recovery requires the exact owned SOURCE and independent identity')
    verify_target_session(recovery.database_url, recovery.database_container, recovery.bootstrap)
    factory = PostgresCompanyTestRetentionSessionFactory(LedgerSupabaseConfiguration(
        recovery.auth_url, anon_key, recovery.reader_url(source_reader_url)))

    async def inventory(token):
        session = await factory.session(token)
        value = await session.read_company_test_retention(rf.Rf1086CompanyTestRetentionQuery(company_id, session.actor_id))
        rf.assert_company_test_retention_target_inventory_matches(expected, value)
        return value

    async def membership_denied(token):
        try:
            await inventory(token)
        except rf.ShareholderRegisterFilingError as error:
            if error.code != rf.ShareholderRegisterFilingErrorCode.NOT_FOUND:
                raise
        else:
            raise ValueError('Independent inventory admitted an unrelated or revoked member')

    async def authentication_denied(token):
        try:
            await inventory(token)
        except ShareholderRegisterFilingAuthenticationError:
            pass
        else:
            raise ValueError('Independent inventory accepted a revoked or deleted session')

    owner = (await factory.session(owner_token)).actor_id
    outsider = (await factory.session(outsider_token)).actor_id
    if owner == outsider:
        raise ValueError('Inventory recovery requires distinct live actors')
    if not any(row.recorded_by == str(owner.subject) for row in expected.records):
        raise ValueError('Inventory lifecycle fixture requires an original recorded actor')
    # The caller derives this genuine local signed fixture only after owned-source
    # binding and canonical owner Auth; never accept an unrelated stateless token.
    try:
        if len(stateless_owner_token) > 65536:
            raise ValueError()
        payload = stateless_owner_token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if claims.get('sub') != str(owner.subject) or 'session_id' in claims:
            raise ValueError()
    except (IndexError, KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('Inventory stateless probe must bind the original owner') from None
    await authentication_denied(stateless_owner_token)
    initial = await inventory(owner_token)
    await membership_denied(outsider_token)
    with _target_connection(recovery) as connection:
        membership = connection.execute('select role,accepted_at from public.company_memberships where company_id=%s and user_id=%s',
            (str(company_id), str(owner.subject))).fetchall()
        if len(membership) != 1 or membership[0][0] != 'owner' or membership[0][1] is None:
            raise ValueError('Inventory recovery requires one accepted original owner')
    for role in ('owner', 'reviewer', 'read_only'):
        with _target_connection(recovery) as connection:
            connection.execute('update public.company_memberships set role=%s where company_id=%s and user_id=%s',
                (role, str(company_id), str(owner.subject)))
        await inventory(owner_token)
    with _target_connection(recovery) as connection:
        connection.execute('update public.company_memberships set role=%s,accepted_at=null where company_id=%s and user_id=%s',
            ('owner', str(company_id), str(owner.subject)))
    await membership_denied(owner_token)
    with _target_connection(recovery) as connection:
        connection.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',
            (membership[0][1], str(company_id), str(owner.subject)))
    await inventory(owner_token)
    with _target_connection(recovery) as connection:
        banned_until = connection.execute('select banned_until from auth.users where id=%s', (str(owner.subject),)).fetchone()[0]
        connection.execute("update auth.users set banned_until=now()+interval '1 hour' where id=%s", (str(owner.subject),))
    try:
        await authentication_denied(owner_token)
    finally:
        with _target_connection(recovery) as connection:
            connection.execute('update auth.users set banned_until=%s where id=%s', (banned_until, str(owner.subject)))
    await inventory(owner_token)
    with _target_connection(recovery) as connection:
        if connection.execute('select count(*) from public.company_memberships where company_id=%s and user_id=%s',
                (str(company_id), str(outsider.subject))).fetchone()[0] != 0:
            raise ValueError('Inventory recovery outsider already has membership')
        connection.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())",
            (str(company_id), str(outsider.subject)))
        removed = connection.execute('delete from public.company_memberships where company_id=%s and user_id=%s returning user_id',
            (str(company_id), str(owner.subject))).fetchall()
        if len(removed) != 1:
            raise ValueError('Original inventory membership was not uniquely revoked')
    await membership_denied(owner_token)
    await inventory(outsider_token)
    with _target_connection(recovery) as connection:
        sessions = connection.execute("select coalesce(jsonb_agg(to_jsonb(s)),'[]'::jsonb) from auth.sessions s where user_id=%s",
            (str(owner.subject),)).fetchone()[0]
        if not sessions:
            raise ValueError('Inventory revocation requires an original live Auth session')
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        verify_target_session(recovery.database_url, recovery.database_container, recovery.bootstrap)
        response = await client.post(recovery.auth_url + '/auth/v1/logout?scope=global',
            headers={'Authorization': 'Bearer ' + owner_token})
        if response.status_code != 204:
            raise ValueError('Independent inventory session revocation failed')
        await authentication_denied(owner_token)
        # Only this disposable TARGET baseline is restored for an independent deletion test.
        with _target_connection(recovery) as connection:
            connection.execute('insert into auth.sessions select * from jsonb_populate_recordset(null::auth.sessions,%s::jsonb)',
                (json.dumps(sessions),))
        if (await factory.session(owner_token)).actor_id != owner:
            raise ValueError('Inventory deletion baseline lacks the captured live session')
        verify_target_session(recovery.database_url, recovery.database_container, recovery.bootstrap)
        response = await client.request('DELETE', recovery.auth_url + '/auth/v1/admin/users/' + str(owner.subject),
            headers={'Authorization': 'Bearer ' + recovery.admin_key}, json={'should_soft_delete': True})
        if response.status_code != 200:
            raise ValueError('Independent inventory Auth soft deletion failed')
        await authentication_denied(owner_token)
    with _target_connection(recovery) as connection:
        if connection.execute('select deleted_at is not null from auth.users where id=%s', (str(owner.subject),)).fetchone() != (True,):
            raise ValueError('Original recorded actor tombstone is missing')
        try:
            with connection.transaction(force_rollback=True):
                connection.execute('delete from auth.users where id=%s', (str(owner.subject),))
        except psycopg.errors.ForeignKeyViolation:
            pass
        else:
            raise ValueError('Historical actor physical-erasure restriction is missing')
    await inventory(outsider_token)
    return CompanyTestInventoryRecoveryReport(expected.record_count, expected.records_sha256,
        initial.observed_at, source_artifact_sha256, True, True, True, True, True, True,
        'blocked-by-preserved-historical-foreign-keys')
