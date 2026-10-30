"""Actual retained-reader schema/role tests; v3 writer activation is not claimed.

The v2 source/preview/bridge use existing closed/public owner commands. V3 annual
inputs, approval, claim and journal rows are explicitly synthetic retained data,
inserted by the designated disposable RF owner with every trigger, FK and FORCE
RLS policy active. Runtime reads use the restricted executor. Immutable fixtures
remain until disposable database teardown; no production grant or SQL is changed.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear
from rf1086_year_source_v2_database_fixture import (
    admitted, amendment_fixture_authority, closed_source_role, withdrawal_fixture_role,
    connection, inactive_inputs, original_fixture, amend, inputs, store as store_v2,
    mint_proof, DATABASE_URL,
)
from test_rf1086_database_runtime import (
    backend_url, rf_fixture_admin_access, fixture as legacy_fixture,
    store as legacy_store, confirmed, insert, rf1086_current_manifest,
    rf1086_current_manifest_hash, rf1086_preview_payload_hash,
)
from test_rf1086_year_source_database import session
from test_rf1086_source_company_guard_database import waiting
from test_rf1086_source_preview import preview_source
from test_rf1086_annual_readiness_v2 import inputs_for
from test_rf1086_source_approval_archive import source_archive

pytestmark = pytest.mark.authority_database


def digest(text):
    return sha256(text.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def source_query(f, actor=None):
    return rf.Rf1086SourceQuery(CompanyId(str(f['seed']['company'])),
        IncomeYear(f['year']), actor or f['store'].actor_id)


def archive_query(f):
    q = source_query(f)
    return rf.Rf1086ArchiveQuery(q.company_id, q.income_year, q.actor_id)


def lock_sql(db, f):
    db.execute('select shareholder_register_filing.lock_year_source_v1(%s,%s)',
        (f['seed']['company'], f['year']))


async def guarded_read(f, *, store=None, query=None, submission=None, ready=None, release=None):
    store = store or f['store']; query = query or source_query(f)
    async with store._transaction() as db:
        if ready is not None:
            ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
        # Historical no-activity fixtures predate CompanyAccess year admission.
        # These are the actual lock keys checked by the owner read RPC, not a
        # fresh source-admission claim. Current application admission is separate.
        await db.execute('select pg_advisory_xact_lock(hashtextextended(%s,157))',
            (str(query.company_id),))
        await db.execute("select pg_advisory_xact_lock(hashtextextended('rf1086:year-source:'||%s||':'||%s,0))",
            (str(query.company_id), str(int(query.income_year))))
        scope = _SourceAdmission(store, db, query, None)
        try:
            result = await scope.read_retained_correction_archive(query, submission or f['submission'])
            if release is not None: await release.wait()
            return result
        finally:
            scope.close()


def read(f, *, held=False, store=None, query=None, submission=None):
    if held:
        return asyncio.run(guarded_read(f, store=store, query=query, submission=submission))
    return asyncio.run((store or f['store']).read_retained_correction_archive(
        query or source_query(f), submission or f['submission']))


@pytest.fixture
def no_activity(legacy_fixture):
    submission, _ = confirmed(legacy_fixture)
    return dict(seed=legacy_fixture, store=legacy_store(legacy_fixture), year=2025,
        submission=rf.SubmissionId(submission), approval=str(legacy_fixture['approval']))


def catalog(db):
    tables = ['source_approval_bindings', 'source_submission_bindings', 'filing_approval_snapshots',
        'production_filing_submissions', 'submission_heads', 'source_previews', 'source_review_bridges']
    return dict(
        tables=db.execute("select c.oid,c.relforcerowsecurity,c.relacl::text from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='shareholder_register_filing' and c.relname=any(%s) order by c.oid", (tables,)).fetchall(),
        triggers=db.execute("select t.oid,t.tgrelid,t.tgenabled,pg_get_triggerdef(t.oid) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='shareholder_register_filing' and c.relname=any(%s) order by t.oid", (tables,)).fetchall(),
        functions=db.execute("select p.oid,p.proowner,p.proacl::text,p.prosrc from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='shareholder_register_filing' order by p.oid").fetchall(),
        memberships=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall())


def retained_v3(seed, role, url, *, capital=False, withdrawal_role=None):
    if capital:
        item = original_fixture(seed, role, withdrawal_role)
        item = amend(item)
        item['source_inputs'] = inputs(item)
    else:
        item = dict(seed=seed, source_role=role, source_inputs=inactive_inputs(seed))
    source = store_v2(item)
    preview = replace(preview_source(source)[0], preview_id=rf.PreviewId(str(uuid4())))
    text = rf.serialize_rf1086_source_preview(preview)
    # The runtime does not receive the closed proof producer or v2 append grant.
    with connection(seed, role) as db:
        mint_proof(db, source)
        db.execute('set local role shareholder_register_filing_executor')
        db.execute('select shareholder_register_filing.append_source_preview_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
            (preview.preview_id.value, source.company_id.value, source.income_year.value,
             source.source_id.value, source.source_sha256, source.case_sha256, digest(text), text))
        db.execute('select shareholder_register_filing.bridge_source_preview_v1(%s,%s,%s)',
            (preview.preview_id.value, digest(text), str(source.confirmed_by.subject)))
        bridge = db.execute('select to_jsonb(b) from shareholder_register_filing.source_review_bridges b where preview_id=%s',
            (preview.preview_id.value,)).fetchone()[0]
    request_id, entitlement_id, approval_id, submission_id = (str(uuid4()) for _ in range(4))
    external = base64.urlsafe_b64encode(sha256(request_id.encode()).digest()).decode().rstrip('=')
    with psycopg.connect(DATABASE_URL) as db:
        at = db.execute('select clock_timestamp()').fetchone()[0]
        insert(db, 'authority_connections.system_user_requests', dict(id=request_id, company_id=seed['company'],
            initiating_owner_user_id=seed['owner'], external_ref=external, status='accepted', preflight_verified_at=at))
        insert(db, 'billing.production_pilot_entitlements', dict(id=entitlement_id, company_id=seed['company'],
            user_id=seed['owner'], income_year=2026, obligation='aksjonaerregisteroppgaven',
            case_profile='rf1086_full_year_v1', status='active', billing_exempt=True,
            system_user_request_id=request_id, system_user_external_reference=external,
            starts_at=at-timedelta(seconds=1), expires_at=at+timedelta(days=1),
            evidence_reference='retained-reader-synthetic-approval', approved_by=seed['owner']))
    annual = rf.build_rf1086_annual_readiness_v2(source, preview, inputs_for(source))
    annual_text = rf.serialize_rf1086_annual_readiness_v2(annual, source, preview)
    review = json.loads(source_archive().source_approval_lineage[0].review_text)
    review.pop('storedReleaseReady')
    review.update(version='rf1086-source-review-v3', binding=bridge, otherOverridesReady=True,
        annualReadiness=dict(schemaVersion='rf1086-annual-readiness-binding-v2',
            proofSha256=annual.proof_sha256, proofTextSha256=digest(annual_text), proofText=annual_text))
    company, actor, year = str(seed['company']), str(seed['owner']), source.income_year.value
    review['scope'].update(companyId=company, incomeYear=year, previewId=preview.preview_id.value,
        sourceId=source.source_id.value, sourceSha256=source.source_sha256,
        entitlementId=entitlement_id, warningCodes=list(annual.required_warning_codes))
    review['permission'].update(company_id=company, submitter_user_id=actor, confirmed_by=actor)
    review['pilot'].update(id=entitlement_id, company_id=company, user_id=actor, income_year=year,
        system_user_request_id=request_id, system_user_external_reference=external)
    review['request'].update(id=request_id, company_id=company, initiating_owner_user_id=actor,
        external_ref=external, preflight_verified_at=at.isoformat())
    review_text = canonical(review)
    manifest = rf.build_rf1086_source_approval_manifest_v3(rf.Rf1086SourceApprovalManifestBasisV3(
        source, preview, annual, source.confirmed_by, entitlement_id, digest(review_text), annual.required_warning_codes))
    manifest_text = rf.serialize_rf1086_source_approval_manifest_v3(manifest)
    with connection(seed, 'shareholder_register_filing_store_owner') as db:
        catalog_before = catalog(db)
        lock_sql(db, dict(seed=seed, year=year))
        # Exact retained shapes, not a public approval/claim writer. Deferred FKs
        # allow bindings before their guarded counterpart rows, as real commands do.
        insert(db, 'shareholder_register_filing.source_approval_bindings', dict(approval_id=approval_id,
            preview_id=preview.preview_id.value, company_id=company, income_year=year,
            source_id=source.source_id.value, source_sha256=source.source_sha256, payload_sha256=digest(text),
            manifest_text=manifest_text, manifest_sha256=manifest.manifest_sha256,
            review_text=review_text, review_sha256=digest(review_text), approved_by=actor))
        insert(db, 'shareholder_register_filing.filing_approval_snapshots', dict(id=approval_id,
            entitlement_id=entitlement_id, preview_id=preview.preview_id.value, company_id=company,
            user_id=actor, income_year=year, obligation='aksjonaerregisteroppgaven',
            case_profile='rf1086_full_year_v1', adapter_version='rf1086-source-production-v1',
            payload_hash=digest(text), manifest_hash=manifest.manifest_sha256,
            manifest=Jsonb(json.loads(manifest_text)), approved_by=actor))
        insert(db, 'shareholder_register_filing.source_submission_bindings', dict(submission_id=submission_id,
            approval_id=approval_id, company_id=company, income_year=year,
            manifest_sha256=manifest.manifest_sha256, payload_sha256=digest(text), claimed_by=actor))
        insert(db, 'shareholder_register_filing.production_filing_submissions', dict(id=submission_id,
            approval_id=approval_id, entitlement_id=entitlement_id, company_id=company, user_id=actor,
            income_year=year, obligation='aksjonaerregisteroppgaven', case_profile='rf1086_full_year_v1',
            adapter_version='rf1086-source-production-v1', payload_hash=digest(text),
            environment='production', status='sending', submitted_by=actor))
        insert(db, 'shareholder_register_filing.submission_heads', dict(company_id=company,
            income_year=year, submission_id=submission_id))
        assert catalog(db) == catalog_before
        assert all(row[1] for row in catalog_before['tables'])
        assert all(row[2] == 'O' for row in catalog_before['triggers'])
    return dict(seed=seed, store=session(seed, url), source=source, preview=preview, annual=annual,
        year=year, submission=rf.SubmissionId(submission_id), approval=approval_id,
        manifest_text=manifest_text, review_text=review_text, entitlement=entitlement_id, item=item,
        catalog=catalog_before)


@pytest.fixture
def v3(admitted, closed_source_role, backend_url):
    return retained_v3(admitted, closed_source_role, backend_url)


@pytest.mark.parametrize('held', [False, True])
def test_legacy_no_activity_reads_actual_original_rows_without_fresh_evidence(no_activity, held):
    f = no_activity
    result = read(f, held=held)
    row = next(row for row in result.production_submissions if row.id == f['submission'].value)
    assert row.user_id == str(f['seed']['owner']) and row.case_profile == 'rf1086_no_activity_v1'
    assert result.source_history is not None and result.source_history.year_sources == ()
    assert result.overrides == result.withdrawal_capture_records == ()
    assert any(row.submission_id == f['submission'].value for row in result.production_events)


@pytest.mark.parametrize('held', [False, True])
def test_v3_exact_stored_source_preview_review_claim_and_complete_capture(v3, held):
    archive = read(v3, held=held)
    assert archive.source_history.year_sources == (v3['source'],)
    assert archive.source_history.source_previews[0].preview == v3['preview']
    assert archive.source_approval_lineage[0].manifest_text == v3['manifest_text']
    assert archive.source_approval_lineage[0].review_text == v3['review_text']
    assert archive.source_submission_claims[0].submission_id == v3['submission']
    payload_sha = digest(rf.serialize_rf1086_source_preview(v3['preview']))
    lineage, claim = archive.source_approval_lineage[0], archive.source_submission_claims[0]
    approval = next(row for row in archive.approvals if row.id == v3['approval'])
    assert lineage.payload_sha256 == lineage.bridge.payload_sha256 == claim.payload_sha256 == approval.payload_hash == payload_sha
    assert lineage.manifest_sha256 == claim.manifest_sha256 == approval.manifest_hash == digest(v3['manifest_text'])
    assert lineage.source_sha256 == lineage.bridge.source_sha256 == v3['source'].source_sha256
    assert archive.submission_head.submission_id == v3['submission']
    # Full retained pure validation, not just a header or manufactured archive.
    wire = rf.serialize_rf1086_archive_v6(archive, query=archive_query(v3))
    assert rf.parse_rf1086_retained_archive(wire, query=archive_query(v3)) == archive


def test_actual_amended_capital_observation_is_not_filtered_from_retained_history(
        admitted, closed_source_role, withdrawal_fixture_role, backend_url):
    f = retained_v3(admitted, closed_source_role, backend_url, capital=True,
        withdrawal_role=withdrawal_fixture_role)
    archive = read(f)
    assert f['source'].governance_projection.chains[0].amendment_count == 1
    assert len(archive.source_history.register_observations) == 2
    assert len(archive.withdrawal_capture_records) == 1
    rf.serialize_rf1086_archive_v6(archive, query=archive_query(f))


@pytest.mark.parametrize('held', [False, True])
@pytest.mark.parametrize('relationship', ['member', 'other-owner', 'revoked-original'])
def test_original_actor_and_current_owner_are_both_required(v3, held, relationship):
    seed = v3['seed']; actor = seed['outsider']
    with psycopg.connect(DATABASE_URL) as db:
        if relationship == 'revoked-original':
            actor = seed['owner']
            db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",
                (seed['company'], actor))
        else:
            insert(db, 'public.company_memberships', dict(company_id=seed['company'], user_id=actor,
                role='owner' if relationship == 'other-owner' else 'read_only', accepted_at=seed['now']))
    client = session(seed, v3['store']._configuration.database_url, actor)
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(v3, held=held, store=client, query=source_query(v3, client.actor_id))


@pytest.mark.parametrize('held', [False, True])
@pytest.mark.parametrize('wrong', ['company', 'year', 'missing-parent'])
def test_exact_scope_and_parent_required(v3, held, wrong):
    q = source_query(v3); identifier = v3['submission']
    if wrong == 'company': q = replace(q, company_id=CompanyId(str(uuid4())))
    elif wrong == 'year': q = replace(q, income_year=IncomeYear(2025))
    else: identifier = rf.SubmissionId(str(uuid4()))
    with pytest.raises((rf.ShareholderRegisterFilingError, rf.Rf1086ProductionError, rf.Rf1086YearSourceError)):
        read(v3, held=held, query=q, submission=identifier)


def test_historical_read_survives_expired_pilot_and_mfa_and_invalidated_approval(v3):
    with connection(v3['seed'], 'shareholder_register_filing_store_owner') as db:
        db.execute("update shareholder_register_filing.filing_approval_snapshots set invalidated_at=clock_timestamp(),invalidation_reason='reader-fixture' where id=%s",
            (v3['approval'],))
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("update billing.production_pilot_entitlements set starts_at=clock_timestamp()-interval '2 days',expires_at=clock_timestamp()-interval '1 day' where id=%s", (v3['entitlement'],))
    client = v3['store']; claims = json.loads(client._verified.claims_json)
    claims['amr'][0]['timestamp'] -= 7200
    client._verified = replace(client._verified, claims_json=json.dumps(claims))
    assert read(v3).source_approval_lineage[0].manifest_text == v3['manifest_text']
    # Final correction admission freshness is outside this raw historical reader.


def test_reader_enumerates_other_actors_and_competing_legacy_roots(no_activity):
    f = no_activity; seed = f['seed']
    entitlement, preview_id, approval, submission = (uuid4() for _ in range(4))
    request, external = seed['request'], seed['external']
    # Independent actor/entitlement/preview. Reusing the first preview would
    # violate its unique current-approval index; reusing its pilot would obscure
    # the original-actor binding this enumeration test is intended to preserve.
    # Both synthetic historical roots reference the one live company request.
    # The second actor gets no fresh filing authority from that reference.
    with psycopg.connect(DATABASE_URL) as db:
        original_request = db.execute('select to_jsonb(r) from authority_connections.system_user_requests r where id=%s',
            (request,)).fetchone()[0]
        insert(db, 'public.company_memberships', dict(company_id=seed['company'], user_id=seed['outsider'],
            role='owner', accepted_at=seed['now']))
        insert(db, 'billing.production_pilot_entitlements', dict(id=entitlement, company_id=seed['company'],
            user_id=seed['outsider'], income_year=2025, obligation='aksjonaerregisteroppgaven',
            case_profile='rf1086_no_activity_v1', status='active', billing_exempt=True,
            system_user_request_id=request, system_user_external_reference=external,
            starts_at=seed['now'], expires_at=seed['now']+timedelta(days=30),
            evidence_reference='retained-reader-second-legacy-owner', approved_by=seed['outsider']))
    with connection(seed, 'shareholder_register_filing_store_owner', actor=seed['outsider']) as db:
        original = db.execute('select hovedskjema_xml,underskjema_xml from shareholder_register_filing.filing_previews where id=%s',
            (seed['preview'],)).fetchone()
        preview = rf.Rf1086Preview(str(preview_id), str(seed['company']), 2025,
            'aksjonaerregisteroppgaven', original[0], original[1], ())
        organization = str(100000000 + seed['company'].int % 899999999)
        payload_hash = rf1086_preview_payload_hash(preview)
        manifest = rf1086_current_manifest(preview, actor_id=str(seed['outsider']), organization_number=organization)
        manifest_hash = rf1086_current_manifest_hash(preview, actor_id=str(seed['outsider']), organization_number=organization)
        insert(db, 'shareholder_register_filing.filing_previews', dict(id=preview_id, company_id=seed['company'],
            income_year=2025, filing='aksjonaerregisteroppgaven', status='ready', preview='second legacy fixture',
            hovedskjema_xml=preview.hovedskjema_xml, underskjema_xml=Jsonb(dict(preview.underskjema_xml)),
            created_by=seed['outsider']))
        insert(db, 'shareholder_register_filing.filing_approval_snapshots', dict(id=approval,
            entitlement_id=entitlement, preview_id=preview_id, company_id=seed['company'], user_id=seed['outsider'],
            income_year=2025, obligation='aksjonaerregisteroppgaven', case_profile='rf1086_no_activity_v1',
            adapter_version='rf1086-production-v1', payload_hash=payload_hash, manifest_hash=manifest_hash,
            manifest=Jsonb(manifest), approved_by=seed['outsider']))
        # No full-year head exists. The unchanged unmanaged-root trigger permits
        # this second legacy root; all normal triggers/FKs/RLS remain active.
        insert(db, 'shareholder_register_filing.production_filing_submissions', dict(id=submission,
            approval_id=approval, entitlement_id=entitlement, company_id=seed['company'], user_id=seed['outsider'],
            income_year=2025, obligation='aksjonaerregisteroppgaven', case_profile='rf1086_no_activity_v1',
            adapter_version='rf1086-production-v1', payload_hash=payload_hash,
            environment='production', status='approved', submitted_by=seed['outsider']))
    for held in (False, True):
        archive = read(f, held=held)
        assert {row.id for row in archive.production_submissions} == {f['submission'].value, str(submission)}
        assert {row.user_id for row in archive.production_submissions} == {str(seed['owner']), str(seed['outsider'])}
        other = next(row for row in archive.approvals if row.id == str(approval))
        assert other.entitlement_id == str(entitlement) and other.preview_id == str(preview_id)
        assert other.manifest_hash == manifest_hash and other.payload_hash == payload_hash

    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select to_jsonb(r) from authority_connections.system_user_requests r where id=%s',
            (request,)).fetchone()[0] == original_request
        assert db.execute("select count(*) from authority_connections.system_user_requests where company_id=%s "
            "and obligation='aksjonaerregisteroppgaven' and status in ('creating','new','accepted','verification_failed')",
            (seed['company'],)).fetchone()[0] == 1
        assert db.execute('select user_id,system_user_request_id from billing.production_pilot_entitlements where id=%s',
            (entitlement,)).fetchone() == (seed['outsider'],request)


@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_held_reader_rejects_wrong_isolation_with_both_actual_guards(v3, isolation):
    async def run():
        # Bind fixture claims only after isolation is fixed; changing isolation
        # after the adapter's set_config SELECT would fail before the target RPC.
        async with await psycopg.AsyncConnection.connect(v3['store']._configuration.database_url,
                row_factory=dict_row) as db, db.transaction():
            await db.execute('set transaction isolation level ' + isolation)
            await db.execute('set local role shareholder_register_filing_executor')
            await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)",
                (str(v3['store'].actor_id.subject), v3['store']._verified.claims_json, v3['store']._verified.claims_json))
            for text in ('select pg_advisory_xact_lock(hashtextextended(%s,157))',
                         "select pg_advisory_xact_lock(hashtextextended('rf1086:year-source:'||%s||':2026',0))"):
                await db.execute(text, (str(v3['seed']['company']),))
            scope = _SourceAdmission(v3['store'], db, source_query(v3), None)
            try:
                with pytest.raises(psycopg.Error, match='rf1086_source_approval_guard_required'):
                    await scope.read_retained_correction_archive(source_query(v3), v3['submission'])
            finally: scope.close()
    asyncio.run(run())


@pytest.mark.parametrize('guard', ['none', 'company-only', 'year-only'])
def test_held_reader_requires_both_guards(v3, guard):
    async def run():
        async with v3['store']._transaction() as db:
            if guard == 'company-only': await db.execute('select pg_advisory_xact_lock(hashtextextended(%s,157))', (str(v3['seed']['company']),))
            if guard == 'year-only': await db.execute("select pg_advisory_xact_lock(hashtextextended('rf1086:year-source:'||%s||':2026',0))", (str(v3['seed']['company']),))
            scope = _SourceAdmission(v3['store'], db, source_query(v3), None)
            try:
                with pytest.raises(psycopg.Error, match='rf1086_source_approval_guard_required'):
                    await scope.read_retained_correction_archive(source_query(v3), v3['submission'])
            finally: scope.close()
    asyncio.run(run())


def test_held_reader_lifetime_and_actual_parent_row_lock(v3):
    async def run():
        scope = None
        async with v3['store']._transaction() as db:
            await db.execute('select shareholder_register_filing.lock_year_source_v1(%s,2026)', (v3['seed']['company'],))
            scope = _SourceAdmission(v3['store'], db, source_query(v3), None)
            await scope.read_retained_correction_archive(source_query(v3), v3['submission'])
            with psycopg.connect(DATABASE_URL) as observer:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    observer.execute('select id from shareholder_register_filing.production_filing_submissions where id=%s for update nowait', (v3['submission'].value,))
            scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):
            await scope.read_retained_correction_archive(source_query(v3), v3['submission'])
    asyncio.run(run())


@pytest.mark.parametrize('revoke', [False, True])
def test_company_wait_rechecks_owner_or_observes_committed_history(v3, revoke):
    async def run():
        task = None
        try:
            with connection(v3['seed'], 'shareholder_register_filing_store_owner') as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (v3['seed']['company'],))
                ready = asyncio.get_running_loop().create_future()
                task = asyncio.create_task(guarded_read(v3, ready=ready))
                await waiting(await ready)
                if revoke:
                    # Explicit disposable membership fixture; actual held owner check follows commit.
                    blocker.execute('reset role')
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (v3['seed']['company'], v3['seed']['owner']))
                else:
                    blocker.execute("update shareholder_register_filing.production_filing_submissions set status='received',feedback_state='processing' where id=%s", (v3['submission'].value,))
            if revoke:
                with pytest.raises(rf.ShareholderRegisterFilingError): await task
            else:
                archive = await task
                assert next(row for row in archive.production_submissions if row.id == v3['submission'].value).status == 'received'
        finally:
            if task is not None and not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_restricted_reader_has_no_store_owner_or_closed_writer_authority(v3):
    async def run():
        async with v3['store']._transaction(snapshot=True, read_only=True) as db:
            row = await (await db.execute("select current_user as role, current_setting('transaction_read_only') as readonly,pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') as owner,has_function_privilege(current_user,'shareholder_register_filing.append_year_source_v2(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)','execute') as append")).fetchone()
            assert row == dict(role='shareholder_register_filing_executor', readonly='on', owner=False, append=False)
    asyncio.run(run())


@pytest.mark.parametrize('held', [False, True])
def test_actual_reader_uses_one_connection_and_correct_transaction(v3, held, monkeypatch):
    transaction = v3['store']._transaction
    traces = []
    @asynccontextmanager
    async def trace(**kwargs):
        async with transaction(**kwargs) as db:
            state = await (await db.execute("select pg_backend_pid() as pid,current_user as role,current_setting('transaction_isolation') as isolation,current_setting('transaction_read_only') as readonly")).fetchone()
            traces.append(state)
            yield db
    monkeypatch.setattr(v3['store'], '_transaction', trace)
    archive = read(v3, held=held)
    assert archive.submission_head.submission_id == v3['submission']
    assert len(traces) == 1
    assert traces[0]['role'] == 'shareholder_register_filing_executor'
    assert traces[0]['isolation'] == ('read committed' if held else 'repeatable read')
    assert traces[0]['readonly'] == ('off' if held else 'on')


def test_held_archive_blocks_real_journal_writer_until_scope_releases(v3):
    async def run():
        task = None
        async def writer(ready):
            async with v3['store']._transaction() as db:
                ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                await db.execute('select shareholder_register_filing.release_production_feedback_reconciliation(%s,%s)',
                    (v3['submission'].value, str(uuid4())))
        try:
            async with v3['store']._transaction() as db:
                await db.execute('select shareholder_register_filing.lock_year_source_v1(%s,2026)', (v3['seed']['company'],))
                scope = _SourceAdmission(v3['store'], db, source_query(v3), None)
                try:
                    await scope.read_retained_correction_archive(source_query(v3), v3['submission'])
                    ready = asyncio.get_running_loop().create_future()
                    task = asyncio.create_task(writer(ready))
                    await waiting(await ready)
                    assert not task.done()
                finally: scope.close()
            await task
        finally:
            if task is not None and not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    with connection(v3['seed'], 'shareholder_register_filing_store_owner') as db:
        assert catalog(db) == v3['catalog']
