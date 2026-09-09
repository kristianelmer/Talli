"""Canonical RF preview, review, simulation and immutable approval preparation."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid5

from .public import (
    GenerateRf1086PreviewCommand, RecordRf1086OverrideCommand,
    AddRf1086ReviewCommentCommand, AcknowledgeRf1086ReviewCommentCommand,
    ConfirmRf1086SimulationCommand, ConfirmRf1086FilingPermissionCommand,
    RecordRf1086TestEvidenceCommand, ApproveRf1086ProductionCommand,
    Rf1086PreparationPersistence, Rf1086PreparedPreview, Rf1086PreparedSimulation,
    Rf1086PreparedApproval, Rf1086Preview, Rf1086PreviewRecord,
    Rf1086SimulationBasis, Rf1086WorkspaceQuery, Rf1086SourceQuery,
    ReadRf1086PreviewQuery, VerifyRf1086SourceEvidenceQuery,
    ShareholderRegisterFilingError, Rf1086RecordedResult, Rf1086WorkspaceSnapshot, OpeningSnapshotId,
)
from .production import (
    _json, _sha256, _js_trim, rf1086_preview_payload_hash,
    rf1086_current_manifest, rf1086_current_manifest_hash,
    rf1086_production_document_order,
)
from .rendering import render_no_activity_rf1086_preview


def _production_preview(record: Rf1086PreviewRecord) -> Rf1086Preview:
    return Rf1086Preview(record.id, record.company_id, record.income_year,
        record.filing, record.hovedskjema_xml or '', record.underskjema_xml,
        tuple(issue.message for issue in record.issues if issue.level == 'warning'))



def _recorded_result(result, *, company_id=None, income_year=None, company_wide=False):
    if (not isinstance(result,Rf1086RecordedResult)
            or (company_id is not None and result.company_id != company_id)
            or (income_year is not None and result.income_year != income_year)
            or (company_wide and result.income_year is not None)):
        raise ShareholderRegisterFilingError.unavailable()
    return result


def validate_workspace(query: Rf1086WorkspaceQuery, result: Rf1086WorkspaceSnapshot):
    if (not isinstance(result,Rf1086WorkspaceSnapshot) or result.company_id != query.company_id
            or result.income_year != query.income_year):
        raise ShareholderRegisterFilingError.unavailable()
    for collection in (result.previews,result.simulations,result.overrides,result.approvals,result.production_submissions):
        if (len({row.id for row in collection}) != len(collection)
                or any(row.company_id != str(query.company_id) or (query.income_year is not None
                    and row.income_year != query.income_year.value) for row in collection)):
            raise ShareholderRegisterFilingError.unavailable()
    for collection in (result.review_comments,result.permissions,result.test_evidence,result.feedback_artifacts):
        if len({row.id for row in collection}) != len(collection) or any(row.company_id != str(query.company_id) for row in collection):
            raise ShareholderRegisterFilingError.unavailable()
    if (any(row.filing not in ('aksjonærregisteroppgaven','aksjonaerregisteroppgaven') for collection in
            (result.previews,result.simulations,result.overrides) for row in collection)
            or any(row.obligation != 'aksjonaerregisteroppgaven' for collection in
                (result.permissions,result.test_evidence,result.approvals,result.production_submissions) for row in collection)
            or len({action.action for action in result.actions}) != len(result.actions)):
        raise ShareholderRegisterFilingError.unavailable()
    return result

def _required_confirmation(value: bool) -> None:
    if value is not True:
        raise ShareholderRegisterFilingError.invalid_input()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def prepare_simulation(command: ConfirmRf1086SimulationCommand, basis: Rf1086SimulationBasis,
                       *, clock: Callable[[], str] = _utc_now) -> Rf1086PreparedSimulation:
    if basis.annual_readiness_ready is not True or basis.hard_review_blocks or basis.blocking_override_targets:
        raise ShareholderRegisterFilingError.company_year_not_admitted()
    _required_confirmation(command.authority_confirmed)
    _required_confirmation(command.preview_confirmed)
    record = basis.preview
    if record.status != 'ready' or not record.hovedskjema_xml:
        raise ShareholderRegisterFilingError.company_year_not_admitted()
    preview = _production_preview(record)
    # Runtime previews use preserved PostgreSQL holder UUIDs. Their lexical
    # order is exactly the original localeCompare order, without ambient locale.
    order = rf1086_production_document_order(preview)
    confirmed_at = clock(); base = f'/api/aksjonaerregister/v1/{preview.income_year}'
    main_id = 'simulated-'+preview.id
    def call(endpoint: str, body: Mapping[str, object]):
        # These fixed request fields have the same ASCII locale/lexical order.
        body_hash = _sha256(_json({name: body[name] for name in sorted(body)}))
        raw = f'{preview.company_id}:{preview.income_year}:{preview.filing}:{endpoint}:{body_hash}'
        return {'endpoint':endpoint,'body_hash':body_hash,'idempotency_key':str(uuid5(NAMESPACE_URL,raw)),
            'status':'prepared','created_at':clock()}
    calls = [call(base+'/1086H',{'content_type':'application/xml','xml':preview.hovedskjema_xml})]
    calls.extend(call(base+'/'+main_id+'/1086U',{'shareholder_id':name,'content_type':'application/xml','xml':preview.underskjema_xml[name]}) for name in order)
    calls.append(call(base+'/'+main_id+f'/bekreft?antall_underskjema={len(order)}',{'antall_underskjema':len(order)}))
    calls.append(call(base+'/forsendelser/simulated-forsendelse-'+preview.id+'/dokumenter?page=0&size=50',{'page':0,'size':50}))
    receipt_id = f'sim-rf1086-{preview.company_id}-{preview.income_year}-{preview.id[:8]}'
    feedback_ids = ['sim-feedback-'+preview.id[:8]]
    result = {'filing':preview.filing,'company_id':preview.company_id,'income_year':preview.income_year,
        'status':'receipt_stored','authority_confirmed_by':str(command.actor_id.subject),'authority_confirmed_at':confirmed_at,
        'preview_confirmed_by':str(command.actor_id.subject),'preview_confirmed_at':confirmed_at,'calls':calls,
        'receipt_id':receipt_id,'feedback_document_ids':feedback_ids,'failure_code':None,'failure_message':None}
    payload_hash = rf1086_preview_payload_hash(preview)
    return Rf1086PreparedSimulation(basis,result,payload_hash,
        f'rf1086:{preview.company_id}:{preview.income_year}:{payload_hash[:16]}',
        tuple({'severity':'accepted','code':'RF1086_ACCEPTED',
            'message':'RF-1086 er akseptert i simuleringsadapter og kvittering er lagret.','documentId':name} for name in feedback_ids),
        {'authority':'simulation','receiptId':receipt_id,'status':'receipt_stored','receivedAt':clock(),'feedbackDocumentIds':feedback_ids},
        {'previewId':preview.id,'payloadHash':payload_hash,'hovedskjemaHash':_sha256(preview.hovedskjema_xml),
            'underskjemaHashes':{name:_sha256(xml) for name,xml in preview.underskjema_xml.items()},'callCount':len(calls),'storedAt':clock()},
        {'filing':preview.filing,'companyId':preview.company_id,'incomeYear':preview.income_year,'payloadHash':payload_hash,
            'hovedskjemaXml':preview.hovedskjema_xml,'underskjemaXml':preview.underskjema_xml})


class Rf1086PreparationService:
    def __init__(self, persistence: Rf1086PreparationPersistence, *, clock: Callable[[], str] = _utc_now):
        self._persistence = persistence
        self._clock = clock

    async def generate_preview(self, command: GenerateRf1086PreviewCommand):
        basis = await self._persistence.load_opening(command)
        if basis.company_id != command.company_id or basis.opening_snapshot_id != command.opening_snapshot_id:
            raise ShareholderRegisterFilingError.not_found()
        prepared = Rf1086PreparedPreview(basis,render_no_activity_rf1086_preview(basis.case))
        return _recorded_result(await self._persistence.record_preview(command,prepared),
            company_id=basis.company_id,income_year=basis.income_year)

    async def record_override(self, command: RecordRf1086OverrideCommand):
        _required_confirmation(command.owner_confirmed)
        normalized = replace(command,field_target=_js_trim(command.field_target),old_value=_js_trim(command.old_value),
            new_value=_js_trim(command.new_value),reason=_js_trim(command.reason))
        if (not normalized.field_target or not (normalized.old_value or normalized.new_value) or not normalized.reason
                or normalized.risk_level not in ('advisory','warning','block')):
            raise ShareholderRegisterFilingError.invalid_input()
        return _recorded_result(await self._persistence.record_override(normalized))

    async def add_review_comment(self, command: AddRf1086ReviewCommentCommand):
        normalized = replace(command,body=_js_trim(command.body))
        if normalized.severity not in ('advisory','hard_block') or not normalized.body:
            raise ShareholderRegisterFilingError.invalid_input()
        return _recorded_result(await self._persistence.add_review_comment(normalized))

    async def acknowledge_review_comment(self, command: AcknowledgeRf1086ReviewCommentCommand):
        # Persisted severity/current access must be checked under the write lock.
        return _recorded_result(await self._persistence.acknowledge_review_comment(command))

    async def confirm_simulation(self, command: ConfirmRf1086SimulationCommand):
        basis = await self._persistence.load_simulation_basis(command)
        if basis.preview.id != str(command.preview_id): raise ShareholderRegisterFilingError.not_found()
        from talli_backend.shared.kernel import CompanyId, IncomeYear
        return _recorded_result(await self._persistence.record_simulation(command,prepare_simulation(command,basis,clock=self._clock)),
            company_id=CompanyId(basis.preview.company_id),income_year=IncomeYear(basis.preview.income_year))

    async def confirm_filing_permission(self, command: ConfirmRf1086FilingPermissionCommand):
        if type(command.production_enabled) is not bool: raise ShareholderRegisterFilingError.invalid_input()
        return _recorded_result(await self._persistence.confirm_filing_permission(command),company_id=command.company_id,company_wide=True)

    async def record_test_evidence(self, command: RecordRf1086TestEvidenceCommand):
        if command.status not in ('accepted','rejected','blocked','pending') or command.environment not in ('test','manual_evidence'):
            raise ShareholderRegisterFilingError.invalid_input()
        optional = lambda value: _js_trim(value) or None if value is not None else None
        normalized = replace(command,test_reference=_js_trim(command.test_reference),feedback_summary=_js_trim(command.feedback_summary),
            receipt_reference=optional(command.receipt_reference),archive_reference=optional(command.archive_reference),
            evidence_url=optional(command.evidence_url),payload_hash=optional(command.payload_hash))
        if not normalized.test_reference: raise ShareholderRegisterFilingError.invalid_input()
        return _recorded_result(await self._persistence.record_test_evidence(normalized),company_id=command.company_id,company_wide=True)

    async def approve_production(self, command: ApproveRf1086ProductionCommand):
        _required_confirmation(command.real_filing_confirmed)
        try: UUID(command.entitlement_id)
        except (ValueError,TypeError,AttributeError): raise ShareholderRegisterFilingError.invalid_input() from None
        basis = await self._persistence.load_approval_basis(command)
        if basis.preview.id != str(command.preview_id) or basis.preview.status != 'ready' or not basis.preview.hovedskjema_xml:
            raise ShareholderRegisterFilingError.company_year_not_admitted()
        preview = _production_preview(basis.preview)
        manifest = rf1086_current_manifest(preview,actor_id=str(command.actor_id.subject),organization_number=basis.organization_number)
        digest = rf1086_current_manifest_hash(preview,actor_id=str(command.actor_id.subject),organization_number=basis.organization_number)
        from talli_backend.shared.kernel import CompanyId, IncomeYear
        return _recorded_result(await self._persistence.record_approval(command,Rf1086PreparedApproval(basis,manifest,digest)),
            company_id=CompanyId(basis.preview.company_id),income_year=IncomeYear(basis.preview.income_year))

    async def workspace(self, query: Rf1086WorkspaceQuery):
        return validate_workspace(query,await self._persistence.workspace(query))

    async def read_preview(self, query: ReadRf1086PreviewQuery):
        result = await self._persistence.preview_record(query)
        if result is not None and (not isinstance(result,Rf1086PreviewRecord) or result.id != str(query.preview_id)):
            raise ShareholderRegisterFilingError.unavailable()
        return result

    async def source_facts(self, query: Rf1086SourceQuery):
        from .source_facts import build_source_facts
        return build_source_facts(query,await self._persistence.source_snapshot(query))

    async def verify_source_evidence(self, query: VerifyRf1086SourceEvidenceQuery) -> bool:
        from .source_facts import verify_source_evidence
        return verify_source_evidence(query,await self._persistence.source_snapshot(query.query))


class OpeningSnapshotService:
    def __init__(self, persistence):
        self._persistence = persistence

    async def record_opening_snapshot(self, command):
        if command.actor_id != self._persistence.actor_id:
            raise ShareholderRegisterFilingError.forbidden()
        try:
            result = await self._persistence.record_opening_snapshot(command)
            if not isinstance(result,OpeningSnapshotId): raise ShareholderRegisterFilingError.unavailable()
            return result
        except ShareholderRegisterFilingError:
            raise
        except ValueError:
            raise ShareholderRegisterFilingError.unavailable() from None
