"""Actual owner fixtures for closed RF v2 SQL; collection performs no IO.

Only released owner commands create positive business rows. Immutable company-
scoped history remains until the owned disposable database is destroyed. A
unique fixture role receives the closed append; runtime roles are unchanged.
"""
from dataclasses import replace
from contextlib import contextmanager
from decimal import Decimal
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import secrets
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg.conninfo import make_conninfo
import pytest

from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.documents.public import document_metadata_sha256
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, IncomeYear, UserId
from governance_register_evidence_amendment_fixture import (
    admitted, amendment_fixture_authority, withdrawal_fixture_role, connection,
    original_document, register_capture, withdrawal, fact, document_fact,
    document_commitment, record_original, DATABASE_URL, ROOT,
    verified, CorporateGovernanceService, _supported_event_request, _ledger_sources,
    _ledger_supported_facts, RecognizeHoldingActionCommand, LedgerService, SupabaseLedgerSession,
)
from test_governance_register_evidence_amendment_database import save, append as append_amendment
from test_governance_reporting_register_evidence_database import adapter as reporting_projection
from test_rf1086_year_source import basis as pure_basis


APPEND = 'shareholder_register_filing.append_year_source_v2(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz)'
LOCK = 'shareholder_register_filing.lock_year_source_v1(uuid,integer)'
GOV_READER = 'corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)'
PRODUCER = 'corporate_governance.prepare_rf_year_source_governance_proof_v1(uuid,integer,text,text)'
RECEIVER = 'shareholder_register_filing.receive_year_source_governance_proof_v1(uuid,integer,text,jsonb,text)'
INVALIDATOR = 'shareholder_register_filing.invalidate_year_source_governance_proofs_v1(uuid)'
PROOFS = 'pg_temp.rf1086_year_source_governance_proofs'
TABLE = 'shareholder_register_filing.year_source_versions'
HEADS = 'shareholder_register_filing.year_source_heads'


@pytest.fixture(scope='module')
def closed_source_role(amendment_fixture_authority):
    role = 'rf_source_v2_fixture_' + uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('create role {} nologin noinherit nobypassrls').format(sql.Identifier(role)))
        db.execute(sql.SQL('grant {} to {} with inherit false,set true granted by {}').format(
            sql.Identifier(role), sql.Identifier(amendment_fixture_authority), sql.Identifier(amendment_fixture_authority)))
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant usage on schema shareholder_register_filing to {}').format(sql.Identifier(role)))
        db.execute(sql.SQL('grant execute on function ' + APPEND + ',' + LOCK + ' to {}').format(sql.Identifier(role)))
        db.execute('set local role corporate_governance_store_owner')
        db.execute(sql.SQL('grant usage on schema corporate_governance to {}').format(sql.Identifier(role)))
        db.execute(sql.SQL('grant execute on function ' + PRODUCER + ' to {}').format(sql.Identifier(role)))
    try:
        yield role
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke all on function ' + APPEND + ',' + LOCK + ' from {}').format(sql.Identifier(role)))
            db.execute(sql.SQL('revoke usage on schema shareholder_register_filing from {}').format(sql.Identifier(role)))
            db.execute('set local role corporate_governance_store_owner')
            db.execute(sql.SQL('revoke all on function ' + PRODUCER + ' from {}').format(sql.Identifier(role)))
            db.execute(sql.SQL('revoke usage on schema corporate_governance from {}').format(sql.Identifier(role)))
            db.execute('reset role')
            db.execute(sql.SQL('revoke {} from {} granted by {}').format(
                sql.Identifier(role), sql.Identifier(amendment_fixture_authority), sql.Identifier(amendment_fixture_authority)))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


@pytest.fixture(scope='module')
def source_login(closed_source_role):
    """Real restricted login; verified request claims remain explicit fixtures."""
    role = 'rf_source_login_' + uuid4().hex
    password = secrets.token_urlsafe(32)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('create role {} login inherit nosuperuser nocreaterole nocreatedb noreplication nobypassrls password {}').format(
            sql.Identifier(role), sql.Literal(password)))
        db.execute(sql.SQL('grant {} to {} with inherit true,set false').format(sql.Identifier(closed_source_role), sql.Identifier(role)))
    @contextmanager
    def connect(seed):
        identity = verified(seed)
        with psycopg.connect(make_conninfo(DATABASE_URL, user=role, password=password)) as db:
            db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true),set_config('talli.authorized_company_roles',%s,true)",
                (str(identity.actor_id.subject),identity.claims_json,identity.claims_json,json.dumps({str(seed['company']):'owner'})))
            db.execute("set local statement_timeout='8s';set local lock_timeout='5s'")
            yield db
    try: yield SimpleNamespace(role=role, connect=connect)
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(sql.SQL('revoke {} from {}').format(sql.Identifier(closed_source_role),sql.Identifier(role)))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def original_fixture(seed, role, withdrawal_role, *, kind='loss_covering_reduction', phase='first_recognized_after_registration'):
    observed, rf_documents = register_capture(seed, kind=kind)
    labels = ('Signed decision', 'Amended articles', 'Registration receipt')
    if kind == 'cash_issue': labels += ('Contribution confirmation',)
    documents = tuple(original_document(seed, label) for label in labels)
    original = record_original(seed, observed, documents,
        kind='cash_capital_increase' if kind == 'cash_issue' else 'loss_coverage_capital_reduction',
        phase='registered' if kind == 'cash_issue' else phase)
    return dict(seed=seed, source_role=role, role='corporate_governance_workflow_executor',
        withdrawal_role=withdrawal_role, **original, original_observation=observed,
        original_rf_docs=rf_documents, gov_documents=documents, replacement=observed,
        replacement_docs=rf_documents, amendments=())


def next_amendment(item):
    withdrawn = withdrawal(item['seed'], item['withdrawal_role'], item['replacement'])
    observed, documents = register_capture(item['seed'], kind=item['replacement'].command.event_kind)
    memo = original_document(item['seed'], 'Correction memo')
    command = gov.AmendSupportedCorporateRegisterEvidence(item['command'].company_id,
        item['command'].income_year, item['command'].actor_id, item['command'].event_id,
        item['anchor'].anchor_sha256, item['amendments'][-1].head if item['amendments'] else None,
        gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(withdrawn.withdrawal_id.value),
            withdrawn.withdrawal_sha256, fact(item['replacement'])), fact(observed),
        document_fact(memo, gov.SupportedCorporateEvidenceKind.CORRECTION_MEMO),
        'Owned replacement after withdrawal')
    return item | dict(amendment_command=command, replacement=observed, replacement_docs=documents,
        originals=tuple(document_commitment(doc) for doc in (*item['gov_documents'], memo, *documents)),
        memo=memo, withdrawn=withdrawn, key=str(uuid4()))


def amend(item):
    pending = next_amendment(item)
    receipt = gov.parse_corporate_register_evidence_amendment(save(pending))
    return pending | {'amendments': (*item['amendments'], receipt)}


def source_fact(value):
    return rf.Rf1086YearRegisterFactV2(rf.Rf1086RegisterObservationId(value.record_id.value),
        value.revision, value.fact_sha256)


def head(value):
    return None if value is None else rf.Rf1086YearGovernanceHeadV2(
        value.amendment_id.value, value.revision, value.amendment_sha256)


def year_projection(view):
    chains = []
    for snapshot in view.register_chains:
        chain = snapshot.chain
        original = chain.anchor.original
        ref = original.event.canonical_facts['shareholderRegisterFact']
        original_fact = rf.Rf1086YearRegisterFactV2(rf.Rf1086RegisterObservationId(ref['record_id']['value']),
            ref['revision'], ref['fact_sha256'])
        links = tuple(rf.Rf1086YearGovernanceLinkV2(head(row.head), head(row.command.expected_head),
            row.command.withdrawal.withdrawal_id.value, row.command.withdrawal.withdrawal_sha256,
            source_fact(row.command.withdrawal.target), source_fact(row.command.replacement), row.recorded_at)
            for row in chain.amendments)
        kind = 'cash_issue' if original.event.event_kind.value == 'cash_capital_increase' else 'loss_covering_reduction'
        chains.append(rf.Rf1086YearGovernanceChainV2(original.event.event_id.value, original.event.company_id,
            original.event.income_year, kind, original.finalization_sha256, chain.anchor.anchor_sha256,
            chain.anchor.original_recorded_at, original_fact, links, snapshot.amendment_count,
            snapshot.enumeration_sha256, head(chain.head), source_fact(chain.effective_register_fact),
            links[-1].recorded_at if links else chain.anchor.original_recorded_at))
    return rf.Rf1086YearGovernanceProjectionV2(view.query.company_id, view.query.income_year,
        view.original.enumeration_sha256, view.chain_enumeration_sha256, view.enumeration_sha256,
        tuple(chains), view.chain_count)


def source_case(observed):
    """Single-event full year derived from the real retained register states."""
    base, _ = pure_basis()
    before, after = observed.command.before, observed.command.after
    kind = observed.command.event_kind
    holder = before.holdings[0]
    assert len(before.holdings) == len(after.holdings) == 1
    if kind == 'cash_issue':
        issued = after.share_count - before.share_count
        event = rf.Rf1086CashIssueEvent(observed.command.effective_at, issued, after.share_count,
            after.nominal_value, (rf.Rf1086FormationAllocation(holder.shareholder_id, issued, Decimal(15000)),),
            True, Decimal(5000) / issued)
    else:
        event = rf.Rf1086LossCoveringReductionEvent(observed.command.effective_at,
            before.share_capital - after.share_capital, before.nominal_value - after.nominal_value,
            after.nominal_value, True, 0)
    shares = rf.Rf1086ShareSnapshot(before.share_capital, after.share_capital, before.nominal_value,
        after.nominal_value, before.share_count, after.share_count, before.share_capital,
        after.share_capital if kind == 'cash_issue' else before.share_capital,
        Decimal(0), Decimal(5000) if kind == 'cash_issue' else Decimal(0))
    return replace(base.case, case_id='owned-year-source-v2',
        company=replace(base.case.company, income_year=observed.command.income_year.value),
        share_snapshot=shares, shareholders=(rf.Rf1086Shareholder(holder.shareholder_id,
            rf.Rf1086ShareholderKind(holder.kind), holder.name, org_number=holder.identifier),),
        shareholder_snapshots=(rf.Rf1086ShareholderSnapshot(holder.shareholder_id,
            before.share_count, after.share_count),), events=(event,))


def inputs(item, *, view=None):
    # Actual public producer/strict decoder. No test-manufactured owner digests.
    view = reporting_projection(item) if view is None else view
    observed = item['replacement']
    case = source_case(observed)
    case = replace(case, company=replace(case.company, org_number=item['seed']['org'], name='Basis Holding AS',
        address='Testveien 1', postal_code='0150', city='Oslo'))
    documents = tuple(rf.Rf1086YearDocumentEvidence(row.document.document_id.value,
        row.document.company_id, row.document.content_sha256, row.document.content_sha256,
        row.document.document_type, row.document.status.value, row.document.byte_length,
        row.document.created_at, document_metadata_sha256(row.document), row.document.income_year)
        for row in (*item['gov_documents'], *item['replacement_docs']))
    ids = tuple(row.document_id for row in documents)
    original = item['original']
    receipt = rf.Rf1086YearGovernanceReceipt(original.event.event_id.value, original.event.company_id,
        original.event.income_year, observed.command.event_kind,
        rf.rf1086_year_source_digest(rf.rf1086_governance_economic_facts(case.events[0])),
        original.finalization_sha256, tuple(sorted(original.signed_artifact_hashes.values())), True,
        item['original_observation'].observation_id.value, item['original_observation'].fact_sha256)
    shares = case.share_snapshot
    command = rf.RecordRf1086YearSource(original.event.company_id, item['command'].actor_id,
        original.event.income_year, case, rf.Rf1086PaidInSourceFacts(shares.previous_paid_in_share_capital,
            shares.current_paid_in_share_capital, shares.previous_paid_in_premium, shares.current_paid_in_premium),
        documents, ids, ids, ids, (rf.Rf1086YearEventEvidence(0, rf.rf1086_year_source_digest(case.events[0]),
            ids, receipt.receipt_id),), True, True, True, False)
    context = rf.Rf1086VerifiedYearSourceContextV2(command.actor_id, True, command.company_id,
        command.income_year, case.company, rf.rf1086_year_source_digest(case.company), documents,
        (rf.Rf1086YearGovernanceReceiptV2(receipt, observed),), True, year_projection(view))
    return command, context


def inactive_inputs(seed, *, year=2026):
    """Actual public documents/projection, with explicit inactive-year command."""
    if year != 2026: admit_source_year(seed, year)
    document = original_document(seed, 'Complete inactive year evidence', year=year).document
    evidence = rf.Rf1086YearDocumentEvidence(document.document_id.value, document.company_id,
        document.content_sha256, document.content_sha256, document.document_type, document.status.value,
        document.byte_length, document.created_at, document_metadata_sha256(document), document.income_year)
    base, _ = pure_basis()
    actor = ActorId(ActorKind.USER, UserId(str(seed['owner'])))
    case = replace(base.case, company=replace(base.case.company, income_year=year,
        org_number=seed['org'], name='Basis Holding AS', address='Testveien 1', postal_code='0150', city='Oslo'))
    command = replace(base, company_id=CompanyId(str(seed['company'])), actor_id=actor,
        income_year=IncomeYear(year), case=case, documents=(evidence,),
        opening_document_ids=(evidence.document_id,), closing_document_ids=(evidence.document_id,),
        paid_in_document_ids=(evidence.document_id,))
    captured = year_projection(reporting_projection({'seed': seed}, year=year))
    context = rf.Rf1086VerifiedYearSourceContextV2(actor, True, command.company_id, command.income_year,
        case.company, rf.rf1086_year_source_digest(case.company), (evidence,), (), True, captured)
    return command, context


def admit_source_year(seed, year):
    """Explicit privileged authorization fixture, separate from RF assertions."""
    with psycopg.connect(DATABASE_URL) as db:
        if db.execute('select 1 from public.company_year_admissions where company_id=%s and accounting_year=%s',
                (seed['company'], year)).fetchone(): return
        assessment, admission, acceptance = (str(uuid4()) for _ in range(3))
        promise = deepcopy(seed['promise'])
        promise.update(accountingYear=year, startsOn=f'{year}-01-01', endsOn=f'{year}-12-31',
            reconstructionRequiredFrom=f'{year}-01-01')
        digest = sha256(json.dumps(promise, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        for table, original, changes in (
            ('company_eligibility_assessments', seed['current'], dict(id=assessment, accounting_year=year, operation_id=str(uuid4()), previous_assessment_id=None)),
            ('company_year_admissions', seed['admission'], dict(id=admission, accounting_year=year, eligibility_assessment_id=assessment,
                company_year_promise=promise, company_year_promise_sha256=digest, reconstruct_from=f'{year}-01-01')),
            ('company_year_acceptances', seed['acceptance'], dict(id=acceptance, accounting_year=year, company_year_admission_id=admission)),
        ):
            db.execute(sql.SQL('insert into public.{0} select (jsonb_populate_record(null::public.{0},to_jsonb(original)||%s::jsonb)).* from public.{0} original where id=%s').format(sql.Identifier(table)), (Jsonb(changes),original))
    with connection(seed, 'corporate_governance_store_owner') as db:
        assert db.execute('select public.company_access_company_year_allows_consequential_v1(%s,%s)', (seed['company'],year)).fetchone()[0]


def pending_governance_event(item):
    """Post real Ledger evidence now; defer only the public Governance completion.

    A separate non-register decision changes reporting inputs without withdrawing
    the selected RF observation. No future producer or foreign row is simulated.
    """
    command = replace(item['command'], event_id=gov.SupportedCorporateEventId(str(uuid4())),
        event_reference=gov.SupportedCorporateEventReference(str(uuid4())), idempotency_key=IdempotencyKey(str(uuid4())),
        phase=gov.SupportedCorporateEventPhase.DECIDED_NOT_REGISTERED,
        document_facts=item['command'].document_facts[:2], shareholder_register_fact=None)
    canonical = CorporateGovernanceService().prepare_supported_event(command)
    request = _supported_event_request(command, canonical)
    with connection(item['seed'], 'corporate_governance_workflow_executor') as db:
        assert db.execute('select corporate_governance.prepare_supported_event_v1(%s,%s)',
            (Jsonb(request), str(item['seed']['owner']))).fetchone()[0]['replay'] is None
    primary, other = _ledger_sources(command, canonical.facts_sha256)
    recognized = RecognizeHoldingActionCommand(command.company_id, command.actor_id, command.correlation_id,
        command.idempotency_key, command.income_year, command.event_date, primary, other, _ledger_supported_facts(command))
    posted = asyncio.run(LedgerService(SupabaseLedgerSession(DATABASE_URL, verified(item['seed']))).recognize_holding_action(recognized))
    return _supported_event_request(command, canonical, accounting_entry_id=gov.AccountingEntryReference(str(posted.entry_id)))


def prepare(db, item, *, previous=None, command=None, context=None, source_id=None):
    if command is None:
        command, context = item['source_inputs']
    if previous is not None:
        command = replace(command, supersedes_source_id=previous.source_id,
            supersedes_source_sha256=previous.source_sha256, correction_reason='Owned exact source correction')
    at = db.execute('select clock_timestamp()').fetchone()[0]
    return rf.prepare_rf1086_year_source_v2(command, context=context,
        source_id=source_id or rf.Rf1086YearSourceId(str(uuid4())), confirmed_at=at, previous=previous)


def mint_proof(db, source, *, changes=None):
    values = dict(company=source.company_id.value, year=source.income_year.value,
        source_sha=source.source_sha256, subject=str(source.command.actor_id.subject))
    values.update(changes or {})
    db.execute('select ' + LOCK.split('(')[0] + '(%s,%s)', (values['company'], values['year']))
    return db.execute('select ' + PRODUCER.split('(')[0] + '(%s,%s,%s,%s)', tuple(values.values())).fetchone()[0]


def append_source(db, source, *, key=None, text=None, changes=None, version=2, proof=True):
    if version == 2 and proof:
        mint_proof(db, source)
    command = source.command
    values = dict(identifier=source.source_id.value, company=source.company_id.value, year=source.income_year.value,
        version=source.version, source_sha=source.source_sha256, request_sha=rf.rf1086_year_source_digest(command),
        key=key or str(uuid4()), previous=command.supersedes_source_id.value if command.supersedes_source_id else None,
        previous_sha=command.supersedes_source_sha256, reason=command.correction_reason,
        snapshot=text if text is not None else (rf.serialize_rf1086_year_source_v2(source) if version == 2 else rf.serialize_rf1086_year_source(source)),
        confirmed_at=source.confirmed_at)
    values.update(changes or {})
    return db.execute('select shareholder_register_filing.append_year_source_v' + str(version)
        + '(' + ','.join('%s' for _ in values) + ')', tuple(values.values())).fetchone()[0]


def store(item, *, previous=None, key=None):
    with connection(item['seed'], item['source_role']) as db:
        source = prepare(db, item, previous=previous)
        append_source(db, source, key=key)
    return source


def rows(item):
    with connection(item['seed'], 'shareholder_register_filing_store_owner') as db:
        return db.execute('select id,version,actor_id,idempotency_key,request_sha256,source_sha256,snapshot_text from '
            + TABLE + ' where company_id=%s order by version', (item['seed']['company'],)).fetchall()
