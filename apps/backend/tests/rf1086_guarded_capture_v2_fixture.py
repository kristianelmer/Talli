"""Real public producers/Document byte service and adapters; SQL/authority are doubles."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import psycopg
from psycopg.pq import TransactionStatus

from talli_backend.application.shareholder_register_source_capture_v2 import ShareholderRegisterSourceCaptureV2
from talli_backend.application.shareholder_register_source_workflow import _document_projection
from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.documents import public as docs
from talli_backend.modules.documents.service import DocumentsService
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IncomeYear, CorrelationId, IdempotencyKey
import test_rf1086_source_context_v2 as basis
from test_shareholder_register_source_workflow import Harness
from test_consequential_adapter_guards import rf_session
from test_postgres_corporate_reporting_register_evidence import payload
from test_postgres_corporate_reporting_evidence import payload as reporting_payload


KEY = IdempotencyKey('guarded-source-v2-capture-001')
CORRELATION = CorrelationId('guarded-source-v2-capture')


def document_wire(record, *, text_dates=False):
    return dict(id=record.document_id.value, company_id=str(record.company_id), income_year=int(record.income_year),
        document_type=record.document_type, name=record.name, linked_to=record.linked_to,
        status=record.status.value, retention_years=record.retention_years, storage_key=record.storage_key,
        content_type=record.content_type, byte_length=record.byte_length, content_sha256=record.content_sha256,
        created_by=str(record.created_by.subject), created_at=record.created_at.isoformat() if text_dates else record.created_at,
        removed_at=None, removal_reason=None)


def source_row(source, key=KEY):
    encode = rf.serialize_rf1086_year_source_v2 if type(source) is rf.Rf1086YearSourceSnapshotV2 else rf.serialize_rf1086_year_source
    return dict(id=source.source_id.value, company_id=source.company_id.value, income_year=int(source.income_year),
        version=source.version, source_sha256=source.source_sha256, actor_id=source.confirmed_by.subject.value,
        confirmed_at=source.confirmed_at, predecessor_id=source.command.supersedes_source_id.value if source.command.supersedes_source_id else None,
        predecessor_sha256=source.command.supersedes_source_sha256, correction_reason=source.command.correction_reason,
        request_sha256=rf.rf1086_year_source_digest(source.command), snapshot_text=encode(source), idempotency_key=str(key))


def observation_row(observation):
    command = observation.command
    return dict(id=observation.observation_id.value, company_id=command.company_id.value,
        income_year=int(command.income_year), version=observation.version, fact_sha256=observation.fact_sha256,
        actor_id=command.actor_id.subject.value, confirmed_at=observation.confirmed_at,
        predecessor_id=command.supersedes_observation_id.value if command.supersedes_observation_id else None,
        predecessor_sha256=command.supersedes_observation_sha256, correction_reason=command.correction_reason,
        request_sha256=rf.rf1086_register_observation_request_digest(command), snapshot_text=rf.serialize_rf1086_register_observation(observation))


def owner_basis(monkeypatch, kind='loss_covering_reduction', count=1):
    records, contents = {}, {}
    template = Harness().record
    command, initial = basis.v2_basis(kind if kind != 'dividend' else 'no_activity')
    prototype = command.documents[0]

    def original(number, *, year=None, document_id=None):
        identity = document_id or basis.identity(number)
        content = (f'%PDF-1.7\nsynthetic original {number}'.encode()).ljust(prototype.byte_length, b' ')
        record = replace(template, document_id=docs.DocumentId(identity), company_id=command.company_id,
            income_year=year or command.income_year, document_type=prototype.document_type,
            status=docs.DocumentStatus(prototype.integrity_status), name=f'Original {number}.pdf',
            storage_key=f'synthetic/{identity}', byte_length=len(content), content_sha256=sha256(content).hexdigest(),
            created_by=command.actor_id, created_at=basis.NOW-timedelta(days=20))
        records[identity], contents[identity] = record, content
        evidence = docs.VerifiedDocumentEvidence(record, record.content_sha256, record.byte_length, record.status)
        return _document_projection(evidence)

    if kind in ('cash_issue', 'loss_covering_reduction'):
        old_digest = basis.digest
        def digest(value):
            if value.startswith('original '):
                number = int(value.split()[-1]); original(number, year=IncomeYear(2024) if 600 < number < 650 else None)
                return records[basis.identity(number)].content_sha256
            if value.startswith('metadata '): return docs.document_metadata_sha256(records[basis.identity(int(value.split()[-1]))])
            return old_digest(value)
        with monkeypatch.context() as patch:
            patch.setattr(basis, 'digest', digest)
            value = basis.coherent(kind, count)
    else:
        if kind == 'dividend':
            old = Harness('dividend'); command = old.command
            projection = original(500, year=old.record.income_year, document_id=old.record.document_id.value)
            command = replace(command, documents=(projection,))
            item = old.view.dividends[0]
            artifacts = tuple(replace(row, content_sha256=projection.content_sha256, byte_length=projection.byte_length) for row in item.artifacts)
            finals = tuple(replace(row, signed_artifact_hashes={a.artifact_kind.value:a.content_sha256 for a in artifacts}) for row in item.finalizations)
            docset = gov.CorporateDocumentSetRecord(item.decision.document_set_id, item.decision.company_id,
                item.decision.income_year, item.decision.decision_id, 'owner_dividend', 'v1', item.decision.decision_hash,
                None, item.decision.created_by, item.decision.created_at)
            lifecycle = gov.CorporateLifecycleSnapshot((item.decision,), (docset,), artifacts, item.events, finals)
        else:
            projection = original(500, document_id=command.documents[0].document_id)
            command = replace(command, documents=(projection,)); lifecycle = gov.CorporateLifecycleSnapshot((),(),(),(),())
        query = gov.CorporateReportingRegisterEvidenceQuery(command.company_id, command.income_year, command.actor_id)
        view = gov.build_reporting_year_register_evidence(query=query,
            basis=gov.CorporateReportingYearBasis(command.company_id, lifecycle, ()), amendments=(), register_chains=())
        value = SimpleNamespace(command=command, initial=initial, view=view, current=None)
    return value, records, contents


class CaptureHarness:
    def __init__(self, monkeypatch, kind='loss_covering_reduction', count=1):
        self.basis, self.records, self.contents = owner_basis(monkeypatch, kind, count)
        self.command = self.basis.command; self.calls=[]; self.guard=False; self.current=None; self.replay=None
        self.fail=None; self.owner=True; self.before_guard=lambda:None; self.committed=False; self.retained={}
        self.clock=basis.NOW+timedelta(days=2);self.saved_transform=lambda row:row;self.key=KEY
        self.failure=psycopg.DatabaseError('synthetic guarded abort')
        self.store=rf_session();self.store._verified=replace(self.store._verified,actor_id=self.command.actor_id)
        company=self.command.case.company
        self.company=SimpleNamespace(id=str(self.command.company_id),role='owner',entity_type='AS',
            identity_confirmed_at=basis.NOW.isoformat(),identity_locked_at=basis.NOW.isoformat(),
            org_number=company.org_number,name=company.name,address=company.address,postal_code=company.postal_code,city=company.city)
        self.admission=dict(companyId=str(self.command.company_id),incomeYear=int(self.command.income_year),
            organizationNumber=company.org_number,legalName=company.name,entityType='AS',address=company.address,
            postalCode=company.postal_code,city=company.city,identityConfirmedAt=self.company.identity_confirmed_at,
            identityLockedAt=self.company.identity_locked_at,acceptedOwner=True,consequentialOperationsAllowed=True)
        owner=self
        class Connection:
            info=SimpleNamespace(transaction_status=TransactionStatus.IDLE)
            async def execute(self,sql,args=()):
                assert self.info.transaction_status is TransactionStatus.INTRANS
                owner.calls.append((sql,args))
                if owner.fail and owner.fail in sql: raise owner.failure
                self.row=None
                if 'lock_year_source_capture_v2' in sql and not owner.owner:raise psycopg.DatabaseError('rf1086_forbidden')
                if 'is_accepted_owner_v1' in sql:self.row={'allowed':owner.owner}
                elif sql.startswith('select * from shareholder_register_filing.year_source_versions'):self.row=owner.replay
                elif 'company_access_read_rf_admission_v1' in sql:self.row={'admission':owner.admission}
                elif 'documents.assert_retained_original_v1' in sql:
                    receipt=owner.retained[args[1]]
                    expected=(receipt.original_id,receipt.document_id.value,str(receipt.company_id),int(receipt.source_income_year),
                        receipt.metadata_sha256,receipt.content_sha256,receipt.byte_length,receipt.retained_at,str(owner.store.actor_id.subject))
                    if args!=expected:raise psycopg.DatabaseError('synthetic original receipt changed')
                    self.row={'document':document_wire(owner.records[args[1]],text_dates=True)}
                elif 'documents.assert_retained_metadata_v1' in sql:
                    if args[0]!=args[1]:raise psycopg.DatabaseError('synthetic metadata changed')
                elif 'read_guarded_reporting_register_evidence_v1' in sql:
                    view=owner.basis.view
                    if view.register_chains:
                        anchors=tuple(x.chain.anchor for x in view.register_chains);histories=tuple(x.chain.amendments for x in view.register_chains)
                        wire=payload(anchors,histories,year=int(owner.command.income_year))
                    else:
                        wire=payload(year=int(owner.command.income_year))
                        if view.original.dividends:
                            item=view.original.dividends[0]
                            docset=gov.CorporateDocumentSetRecord(item.decision.document_set_id,item.decision.company_id,item.decision.income_year,
                                item.decision.decision_id,'owner_dividend','v1',item.decision.decision_hash,None,item.decision.created_by,item.decision.created_at)
                            wire['reporting_inputs']=reporting_payload(life=gov.CorporateLifecycleSnapshot((item.decision,),(docset,),item.artifacts,item.events,item.finalizations))
                    wire.update(company_id=str(owner.command.company_id),chain_enumeration_sha256=view.chain_enumeration_sha256)
                    wire['reporting_inputs'].update(companyId=str(owner.command.company_id),incomeYear=int(owner.command.income_year))
                    self.row={'result':wire}
                elif 'from shareholder_register_filing.register_observations' in sql:self.row=observation_row(owner.basis.current)
                elif 'from shareholder_register_filing.year_source_heads' in sql:self.row=owner.current
                elif 'clock_timestamp()' in sql:self.row={'now':owner.clock}
                elif 'documents.retain_verified_rf_evidence_v1' in sql:self.row=document_wire(owner.records[args[2]])
                elif 'append_year_source_v2(' in sql:
                    owner.current=owner.saved_transform(source_row(rf.parse_rf1086_year_source_v2(args[10]),IdempotencyKey(args[6])));owner.append_args=args
                return self
            async def fetchone(self):return self.row
        self.connection=Connection()
        @asynccontextmanager
        async def transaction(**options):
            snapshot=options.get('snapshot',False);old_current=owner.current
            if not snapshot:owner.before_guard()
            owner.guard=not snapshot;owner.connection.info.transaction_status=TransactionStatus.INTRANS
            try:
                yield owner.connection
                if not snapshot:owner.committed=True
            except BaseException:
                owner.current=old_current;raise
            finally:owner.guard=False;owner.connection.info.transaction_status=TransactionStatus.IDLE
        self.store._transaction=transaction
        class Sessions:
            async def session(self,token):return owner.store
        class Company:
            async def company_record(self,token,*,company_id):
                assert not owner.guard;owner.calls.append(('company',company_id));return SimpleNamespace(company=owner.company)
        class Persistence:
            actor_id=owner.command.actor_id
            async def get_document(self,document_id):return owner.records[document_id.value]
            async def refresh_actor_role(self,company_id):return 'owner' if owner.owner else None
            async def retain_verified_original(self,document,content):
                assert not owner.guard and content==owner.contents[document.document_id.value]
                receipt=docs.RetainedDocumentOriginalReceipt(basis.identity(9000+int(document.document_id.value.replace('-',''),16)),
                    document.document_id,document.company_id,document.income_year,docs.document_metadata_sha256(document),
                    document.content_sha256,len(content),basis.NOW+timedelta(days=1))
                owner.retained[document.document_id.value]=receipt;return receipt
        class Storage:
            async def read_object(self,*,bucket,storage_key):
                assert not owner.guard;identity=storage_key.split('/')[-1];owner.calls.append(('bytes',identity))
                return docs.StoredDocumentObject(owner.contents[identity],'application/pdf')
        class Documents:
            async def session(self,token):return DocumentsService(Persistence(),Storage())
        self.workflow=ShareholderRegisterSourceCaptureV2(Sessions(),Company(),Documents())

    def capture(self):
        return asyncio.run(self.workflow.capture_year_source('synthetic-token',self.command,
            idempotency_key=self.key,correlation_id=CORRELATION))
