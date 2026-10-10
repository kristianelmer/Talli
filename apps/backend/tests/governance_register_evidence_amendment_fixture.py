"""Owned amendment fixtures using released restricted owner commands.

No amendment SQL is simulated. Immutable positive history stays in the uniquely
owned disposable database; only temporary role grants are removed. Local import
and collection do not prove PostgreSQL, RLS, byte storage or concurrency behavior.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_document_originals import _receipt, _snapshot_document
from talli_backend.adapters.postgres_shareholder_register_filing import PostgresShareholderRegisterFilingSession
from talli_backend.adapters.supabase_corporate_governance import _recorded_supported_event, _supported_event_request
from talli_backend.adapters.supabase_documents import _document
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerSession, _VerifiedActor, _fact_reference_payload
from talli_backend.application.corporate_governance_workflow import _ledger_sources, _ledger_supported_facts
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.modules.documents.public import DocumentRecord, RetainedDocumentOriginalReceipt, document_metadata_sha256
from talli_backend.modules.ledger.public import RecognizeHoldingActionCommand
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, LocalDate, Money, UserId
from test_annual_purchase_basis_runtime import admitted
from test_corporate_governance_supported_events import command as corporate_command, capital_facts, reduction_facts
from test_rf1086_register_observation import basis as register_basis

DATABASE_URL = os.environ.get('DATABASE_URL', '')
ROOT = Path(__file__).resolve().parents[3]
WITHDRAW = 'shareholder_register_filing.append_register_observation_withdrawal_v1(uuid,integer,uuid,integer,text,text,text)'
EVENT_DATE = date(2026, 9, 1)
ROLES = ('documents_store_owner', 'documents_executor', 'shareholder_register_filing_store_owner',
    'shareholder_register_filing_executor', 'ledger_store_owner', 'ledger_executor',
    'corporate_governance_store_owner', 'corporate_governance_workflow_executor', 'banking_executor')


@pytest.fixture(scope='module')
def amendment_fixture_authority():
    """Borrow only missing SET edges; restore each exact original self-grant."""
    assert DATABASE_URL, 'DATABASE_URL must identify the owned disposable database'
    changed = []
    with psycopg.connect(DATABASE_URL) as db:
        principal, bypass = db.execute('select current_user,rolbypassrls from pg_roles where rolname=current_user').fetchone()
        assert bypass
        for role in ROLES:
            if db.execute("select pg_has_role(current_user,%s,'SET')", (role,)).fetchone()[0]: continue
            prior = db.execute('select admin_option,inherit_option,set_option from pg_auth_members where roleid=%s::regrole and member=current_user::regrole and grantor=member', (role,)).fetchone()
            db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(role), sql.Identifier(principal), sql.Identifier(principal)))
            changed.append((role, prior))
    try: yield principal
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            for role, prior in reversed(changed):
                db.execute(sql.SQL('revoke {} from {} granted by {}').format(sql.Identifier(role), sql.Identifier(principal), sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by {}').format(
                        sql.Identifier(role), sql.Identifier(principal), *(sql.SQL(str(v).lower()) for v in prior), sql.Identifier(principal)))


@pytest.fixture(scope='module')
def withdrawal_fixture_role(amendment_fixture_authority):
    role = 'gov_amendment_withdrawal_' + uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL('create role {} nologin noinherit nobypassrls').format(sql.Identifier(role)))
        db.execute(sql.SQL('grant {} to {} with inherit false,set true').format(sql.Identifier(role), sql.Identifier(amendment_fixture_authority)))
        db.execute('set local role shareholder_register_filing_store_owner')
        db.execute(sql.SQL('grant usage on schema shareholder_register_filing to {}').format(sql.Identifier(role)))
        db.execute(sql.SQL('grant execute on function ' + WITHDRAW + ' to {}').format(sql.Identifier(role)))
    try: yield role
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute(sql.SQL('revoke all on function ' + WITHDRAW + ' from {}').format(sql.Identifier(role)))
            db.execute(sql.SQL('revoke usage on schema shareholder_register_filing from {}').format(sql.Identifier(role)))
            db.execute('reset role')
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def verified(seed, actor=None, *, fresh=True):
    actor = actor or seed['owner']
    with psycopg.connect(DATABASE_URL) as db:
        at = db.execute('select clock_timestamp()').fetchone()[0].timestamp() - (1 if fresh else 7200)
    identity = ActorId(ActorKind.USER, UserId(str(actor)))
    return _VerifiedActor(identity, json.dumps({'sub': str(actor), 'role': 'authenticated', 'aal': 'aal2', 'amr': [{'method': 'totp', 'timestamp': at}]}))


@contextmanager
def connection(seed, role, *, actor=None, fresh=True, isolation=None):
    identity = verified(seed, actor, fresh=fresh)
    with psycopg.connect(DATABASE_URL) as db:
        if isolation: db.execute(sql.SQL('set transaction isolation level {}').format(sql.SQL(isolation)))
        db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true),set_config('talli.authorized_company_roles',%s,true)",
            (str(identity.actor_id.subject), identity.claims_json, identity.claims_json, json.dumps({str(seed['company']): 'owner'})))
        db.execute("set local statement_timeout='8s';set local lock_timeout='5s'")
        yield db


@dataclass(frozen=True)
class OriginalDocument:
    document: DocumentRecord
    content: bytes
    receipt: RetainedDocumentOriginalReceipt


def original_document(seed, label, *, year=2026):
    """Actual stage/finalize/retain calls and actual local bytes, without IO mocks."""
    identity = str(uuid4()); content = ('%PDF-1.7\nOwned ' + label + ' ' + identity).encode()
    digest = sha256(content).hexdigest()
    with connection(seed, 'documents_executor') as db:
        request = dict(documentId=identity, companyId=str(seed['company']), incomeYear=year,
            documentType='corporate_document', name=label + '.pdf', linkedTo='workspace',
            storageKey=f"{seed['company']}/{year}/{identity}/original.pdf", contentType='application/pdf',
            declaredByteLength=len(content), finalStatus='attached')
        db.execute('select * from documents.stage_upload_v1(%s,%s)', (Jsonb(request), str(seed['owner'])))
        with db.cursor(row_factory=dict_row) as cur:
            doc = _document(cur.execute('select * from documents.finalize_upload_v1(%s,%s,%s,%s)',
                (identity, len(content), digest, str(seed['owner']))).fetchone())
        metadata = document_metadata_sha256(doc)
        raw = db.execute('select documents.retain_original_v1(%s,%s,%s,%s,%s,%s,%s)',
            (identity, seed['company'], metadata, digest, len(content), content, str(seed['owner']))).fetchone()[0]
        actual = _snapshot_document(raw['document'])
        assert actual == doc
        db.execute('select documents.assert_retained_metadata_v1(%s,%s)', (document_metadata_sha256(actual), metadata))
        receipt = _receipt(raw['receipt'])
    return OriginalDocument(doc, content, receipt)


def register_capture(seed, *, kind='loss_covering_reduction', documents=None, predecessor=None, changes=None):
    records = documents or tuple(original_document(seed, name, year=2024) for name in ('Register before', 'Register after', 'Registration'))
    identities = verified(seed)
    command, context = register_basis(kind)
    evidence = tuple(rf.Rf1086RegisterDocumentEvidence(
        row.document.document_id.value, row.document.company_id, row.document.content_sha256,
        row.document.content_sha256, row.document.byte_length, row.document.document_type,
        row.document.status.value, row.document.created_at, document_metadata_sha256(row.document), role,
        row.document.income_year) for row, role in zip(records, ('register_before', 'register_after', 'registration')))
    before = command.before
    if kind == 'cash_issue':
        before = replace(before, share_capital=Decimal(50000), share_count=500, nominal_value=Decimal(100), holdings=(replace(before.holdings[0], share_count=500),))
        after = replace(before, share_capital=Decimal(60000), share_count=600, holdings=(replace(before.holdings[0], share_count=600),))
    elif kind == 'cash_nominal_increase':
        before = replace(before, share_capital=Decimal(50000), nominal_value=Decimal(500))
        after = replace(before, share_capital=Decimal(60000), nominal_value=Decimal(600))
    else:
        before = replace(before, share_capital=Decimal(50000), nominal_value=Decimal(500))
        after = replace(before, share_capital=Decimal(30000), nominal_value=Decimal(300))
    values = dict(company_id=CompanyId(str(seed['company'])), actor_id=identities.actor_id,
        income_year=IncomeYear(2026), effective_at=datetime.combine(EVENT_DATE, datetime.min.time()),
        before=before, after=after, documents=evidence)
    command = replace(command, **(values | (changes or {})))
    if predecessor is not None:
        command = replace(command, supersedes_observation_id=predecessor.observation_id,
            supersedes_observation_sha256=predecessor.fact_sha256, correction_reason='Owned corrected source')
    context = replace(context, actor_id=command.actor_id, company_id=command.company_id,
        income_year=command.income_year, documents=evidence)
    store = PostgresShareholderRegisterFilingSession(LedgerSupabaseConfiguration('https://local.example.test', '', DATABASE_URL),
        identities, access_token='fixture-only', billing=None, documents=None, company_access=None)
    captured = asyncio.run(store.record_register_observation(command, context=context, idempotency_key=IdempotencyKey(str(uuid4()))))
    return captured, records


def withdrawal(seed, role, observation, *, key=None, db=None):
    def execute(conn):
        raw = conn.execute('select shareholder_register_filing.append_register_observation_withdrawal_v1(%s,%s,%s,%s,%s,%s,%s)',
            (seed['company'], 2026, observation.observation_id.value, observation.version,
             observation.fact_sha256, 'Wrong register evidence; retained for history', key or str(uuid4()))).fetchone()[0]
        return rf.parse_rf1086_register_observation_withdrawal(raw)
    if db is not None: return execute(db)
    with connection(seed, role) as conn: return execute(conn)


def fact(observation):
    return gov.SupportedCorporateSourceFact(gov.CorporateSourceReference(observation.observation_id.value), observation.version, observation.fact_sha256)


def document_fact(original, kind, *, revision=1):
    return gov.SupportedCorporateDocumentFact(gov.DocumentReference(original.document.document_id.value), kind, revision, original.document.content_sha256)


def document_commitment(original, *, revision=1):
    r = original.receipt
    return gov.CorporateDocumentOriginalCommitment(gov.CorporateSourceReference(r.original_id),
        gov.DocumentReference(r.document_id.value), r.company_id, r.source_income_year, revision,
        r.metadata_sha256, r.content_sha256, r.byte_length, r.retained_at)


def imported_bank_fact(seed):
    """Synthetic local statement through public import; no remote bank assertion."""
    digest = sha256(('Owned statement ' + str(uuid4())).encode()).hexdigest()
    with connection(seed, 'banking_executor') as db:
        result = db.execute('select banking.import_statement_v1(%s,%s)', (Jsonb(dict(companyId=str(seed['company']), incomeYear=2026,
            idempotencyKey=str(uuid4()), transactions=[dict(transactionDate=EVENT_DATE.isoformat(), text='Owned cash contribution', amount='15000.00', sourceHash=digest)])), str(seed['owner']))).fetchone()[0]
        assert result['importedCount'] == 1
        items = db.execute("select items from banking.list_records_v1('transactions',%s::uuid[],null,100,%s)", ([seed['company']], str(seed['owner']))).fetchone()[0]
        row = next(item for item in items if item['sourceHash'] == digest)
    return gov.SupportedCorporateBankFact(gov.BankTransactionReference(row['transactionId']), LocalDate(EVENT_DATE), Money.nok('15000.00'), digest)


def record_original(seed, observation, documents, *, kind='loss_coverage_capital_reduction', phase='first_recognized_after_registration'):
    """Canonical Governance + exact production Ledger construction + public SQL."""
    evidence = gov.SupportedCorporateEvidenceKind
    kinds = (evidence.SIGNED_DECISION, evidence.AMENDED_ARTICLES, evidence.REGISTRATION_RECEIPT)
    cash = kind == 'cash_capital_increase'
    if cash: kinds += (evidence.CONTRIBUTION_CONFIRMATION,)
    assert len(documents) == len(kinds)
    docfacts = tuple(document_fact(row, tag) for row, tag in zip(documents, kinds))
    identities = verified(seed)
    command = replace(corporate_command(kind=gov.SupportedCorporateEventKind(kind), phase=gov.SupportedCorporateEventPhase(phase),
        facts=capital_facts() if cash else reduction_facts(), documents=docfacts,
        bank_fact=imported_bank_fact(seed) if cash else None, shareholder_register_fact=fact(observation)),
        company_id=CompanyId(str(seed['company'])), actor_id=identities.actor_id,
        event_id=gov.SupportedCorporateEventId(str(uuid4())), event_reference=gov.SupportedCorporateEventReference(str(uuid4())),
        idempotency_key=IdempotencyKey(str(uuid4())), correlation_id=CorrelationId('owned-amendment-original'))

    def post_and_record(cmd):
        canonical = CorporateGovernanceService().prepare_supported_event(cmd)
        request = _supported_event_request(cmd, canonical)
        with connection(seed, 'corporate_governance_workflow_executor') as db:
            assert db.execute('select corporate_governance.prepare_supported_event_v1(%s,%s)', (Jsonb(request), str(seed['owner']))).fetchone()[0]['replay'] is None
        primary, other = _ledger_sources(cmd, canonical.facts_sha256)
        sources = [_fact_reference_payload(primary, primary=True), *(_fact_reference_payload(item, primary=False) for item in other)]
        recognized = RecognizeHoldingActionCommand(cmd.company_id, cmd.actor_id, cmd.correlation_id, cmd.idempotency_key,
            cmd.income_year, cmd.event_date, primary, other, _ledger_supported_facts(cmd))
        posted = asyncio.run(LedgerService(SupabaseLedgerSession(DATABASE_URL, identities)).recognize_holding_action(recognized))
        request = _supported_event_request(cmd, canonical, accounting_entry_id=gov.AccountingEntryReference(str(posted.entry_id)))
        with connection(seed, 'corporate_governance_workflow_executor') as db:
            raw = db.execute('select corporate_governance.complete_supported_event_v1(%s,%s)', (Jsonb(request), str(seed['owner']))).fetchone()[0]
        return _recorded_supported_event(raw), sources, request

    phases = ('binding_subscription', 'restricted_payment') if cash else ('decided_not_registered',) if phase == 'registered' else ()
    for earlier in phases:
        predecessor = replace(command, event_id=gov.SupportedCorporateEventId(str(uuid4())), idempotency_key=IdempotencyKey(str(uuid4())),
            phase=gov.SupportedCorporateEventPhase(earlier), shareholder_register_fact=None,
            bank_fact=command.bank_fact if earlier == 'restricted_payment' else None,
            document_facts=(docfacts[0],) if earlier == 'binding_subscription' else docfacts[:2] if earlier == 'decided_not_registered' else docfacts)
        post_and_record(predecessor)
    original, sources, request = post_and_record(command)
    anchor = gov.anchor_supported_corporate_event_evidence(original, original_actor_id=command.actor_id.subject)
    return dict(command=command, original=original, anchor=anchor, ledger_sources=sources, original_request=request)
