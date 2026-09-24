"""Canonical RF preview, review, simulation and immutable approval preparation."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid5

from .public import (
    GenerateRf1086PreviewCommand, GenerateRf1086SourcePreview, Rf1086SourcePreview, RecordRf1086OverrideCommand,
    AddRf1086ReviewCommentCommand, AcknowledgeRf1086ReviewCommentCommand,
    ConfirmRf1086SimulationCommand, ConfirmRf1086FilingPermissionCommand,
    RecordRf1086TestEvidenceCommand, ApproveRf1086ProductionCommand,
    Rf1086PreparationPersistence, Rf1086PreparedPreview, Rf1086PreparedSimulation,
    Rf1086PreparedApproval, Rf1086Preview, Rf1086PreviewRecord,
    Rf1086SimulationBasis, Rf1086WorkspaceQuery, Rf1086SourceQuery, Rf1086ArchiveQuery, Rf1086ArchiveSnapshot,
    Rf1086SimulationRecord, Rf1086ReviewCommentRecord, Rf1086FilingPermissionRecord, Rf1086TestEvidenceRecord,
    Rf1086ApprovalRecord, Rf1086ProductionSubmissionRecord, Rf1086ArchiveProductionEventRecord,
    Rf1086ArchiveFeedbackArtifactRecord, Rf1086ProductionError,
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

def _validate_archive_source(query: Rf1086ArchiveQuery, result: Rf1086ArchiveSnapshot, *, include_production: bool = True):
    if (not isinstance(result,Rf1086ArchiveSnapshot) or result.company_id != query.company_id
            or result.income_year != query.income_year):
        raise ShareholderRegisterFilingError.unavailable()
    collections = (
        (result.previews,Rf1086PreviewRecord),(result.simulations,Rf1086SimulationRecord),
        (result.review_comments,Rf1086ReviewCommentRecord),(result.permissions,Rf1086FilingPermissionRecord),
        (result.test_evidence,Rf1086TestEvidenceRecord),
    )
    if include_production:
        collections += (
            (result.approvals,Rf1086ApprovalRecord),(result.production_submissions,Rf1086ProductionSubmissionRecord),
            (result.production_events,Rf1086ArchiveProductionEventRecord),
            (result.feedback_artifacts,Rf1086ArchiveFeedbackArtifactRecord),
        )
    for collection,record_type in collections:
        if (any(not isinstance(row,record_type) or row.company_id != str(query.company_id) for row in collection)
                or len({row.id for row in collection}) != len(collection)):
            raise ShareholderRegisterFilingError.unavailable()
    if any(row.income_year != query.income_year.value or row.filing not in ('aksjonærregisteroppgaven','aksjonaerregisteroppgaven')
            for collection in (result.previews,result.simulations) for row in collection):
        raise ShareholderRegisterFilingError.unavailable()
    if (any(row.target != 'rf1086_preview' for row in result.review_comments)
            or any(row.obligation != 'aksjonaerregisteroppgaven' for collection in (result.permissions,result.test_evidence) for row in collection)):
        raise ShareholderRegisterFilingError.unavailable()
    referenced = {row.authority_test_run_id for row in result.simulations
        if row.mode == 'test_authority' and row.authority_test_run_id is not None}
    if {row.id for row in result.test_evidence} != referenced:
        raise ShareholderRegisterFilingError.unavailable()
    if not include_production:
        return result
    try:
        _validate_archive_production(query, result)
    except (ValueError, TypeError, KeyError, AttributeError, Rf1086ProductionError):
        raise ShareholderRegisterFilingError.unavailable() from None
    return result


def _validate_archive_production(query, result):
    def require(condition):
        if not condition:
            raise ValueError("RF archive production evidence is inconsistent")

    def valid_hash(value):
        return isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None

    previews = {row.id: row for row in result.previews}
    approvals = {row.id: row for row in result.approvals}
    submissions = {row.id: row for row in result.production_submissions}
    from . import public as rf
    lineage = result.source_approval_lineage
    require(all(isinstance(row, rf.Rf1086ArchiveSourceApprovalLineage) for row in lineage))
    require(len({row.approval_id for row in lineage}) == len(lineage))
    source_approvals = {row.id for row in result.approvals if row.case_profile == 'rf1086_full_year_v1'}
    require({row.approval_id for row in lineage} == source_approvals)
    retained = {row.approval_id: row for row in lineage}
    for row in (*result.approvals, *result.production_submissions, *result.production_events):
        require(row.income_year == int(query.income_year))
    for row in result.approvals:
        require(row.obligation == "aksjonaerregisteroppgaven" and row.preview_id in previews)
        if row.case_profile == 'rf1086_full_year_v1':
            _validate_archive_source_approval(query, row, previews[row.preview_id], retained[row.id], require)
            prior = row.manifest['predecessor']
            if prior is not None:
                require(prior['submissionId'] in submissions)
                prior_submission = submissions[prior['submissionId']]
                require(prior_submission.approval_id in approvals
                        and prior_submission.status in ('accepted', 'rejected')
                        and approvals[prior_submission.approval_id].manifest_hash == prior['manifestSha256'])
            continue
        require(row.case_profile == 'rf1086_no_activity_v1'
                and previews[row.preview_id].source != 'rf1086-full-year-v1'
                and row.manifest.get('schemaVersion') != 'production-source-approval-v1')
        preview = _production_preview(previews[row.preview_id])
        require(row.payload_hash == rf1086_preview_payload_hash(preview))
        require(row.manifest_hash == rf1086_current_manifest_hash(preview,
            actor_id=row.user_id, organization_number=row.manifest["organizationNumber"],
            approved_manifest=row.manifest))
    for row in result.production_submissions:
        require(row.obligation == "aksjonaerregisteroppgaven" and row.environment == "production")
        # Full-year send and its historical journal validation are a successor
        # boundary. Never publish a partial archive as complete production proof.
        require(row.case_profile == 'rf1086_no_activity_v1')
        require(row.approval_id in approvals)
        approval = approvals[row.approval_id]
        require((row.entitlement_id, row.user_id, row.payload_hash, row.case_profile, row.adapter_version)
            == (approval.entitlement_id, approval.user_id, approval.payload_hash, approval.case_profile, approval.adapter_version))
        if row.supersedes_submission_id is not None:
            require(row.supersedes_submission_id in submissions and row.supersedes_submission_id != row.id)
        seen = {row.id}
        predecessor = row.supersedes_submission_id
        while predecessor is not None:
            require(predecessor not in seen and predecessor in submissions)
            seen.add(predecessor)
            predecessor = submissions[predecessor].supersedes_submission_id
    document_ids = set()
    artifact_hashes = {identity: set() for identity in submissions}
    for artifact in result.feedback_artifacts:
        require(artifact.submission_id in submissions and artifact.document_id not in document_ids)
        document_ids.add(artifact.document_id)
        require(valid_hash(artifact.sha256) and type(artifact.byte_length) is int and 1 <= artifact.byte_length <= 10485760)
        require(artifact.sha256 not in artifact_hashes[artifact.submission_id])
        artifact_hashes[artifact.submission_id].add(artifact.sha256)
        require(isinstance(artifact.authority_reference, str) and 1 <= len(artifact.authority_reference) <= 500)
        submission = submissions[artifact.submission_id]
        if submission.feedback_state in ("accepted", "rejected"):
            require(artifact.classification == submission.feedback_state)
    for submission in result.production_submissions:
        require(type(submission.feedback_artifact_count) is int
            and submission.feedback_artifact_count == len(artifact_hashes[submission.id]))
        if submission.status in ("accepted", "rejected"):
            require(submission.feedback_state == submission.status)
        if submission.feedback_state in ("accepted", "rejected"):
            require(submission.status == submission.feedback_state and submission.feedback_artifact_count > 0)
            require(any(event.submission_id == submission.id
                and event.operation_name.startswith("reconciliation:")
                and event.operation_state == "succeeded"
                and event.resulting_status == submission.feedback_state
                and set(event.artifact_hashes) == artifact_hashes[submission.id]
                for event in result.production_events))
    for event in result.production_events:
        require(event.submission_id in submissions)
        require(all(valid_hash(value) for value in event.artifact_hashes)
            and len(set(event.artifact_hashes)) == len(event.artifact_hashes)
            and set(event.artifact_hashes) <= artifact_hashes[event.submission_id])
        require(event.body_hash is None or valid_hash(event.body_hash))


def _validate_archive_source_approval(query, approval, projection, lineage, require):
    """Rebuild historical approved identity without asking for today's head/facts."""
    from . import public as rf
    from talli_backend.shared.kernel import ActorId, ActorKind, UserId

    source, preview, bridge = lineage.source, lineage.source_preview, lineage.bridge
    require(isinstance(source, rf.Rf1086YearSourceSnapshot)
            and isinstance(preview, rf.Rf1086SourcePreview)
            and isinstance(bridge, rf.Rf1086ArchiveSourceReviewBridge))
    try:
        rf.assert_rf1086_year_source_integrity(source)
        rf.assert_rf1086_source_preview_matches(preview, source)
        payload_sha = _sha256(rf.serialize_rf1086_source_preview(preview))
    except rf.Rf1086YearSourceError:
        raise ValueError('RF retained source identity is inconsistent') from None
    expected = (preview.preview_id.value, str(query.company_id), int(query.income_year),
                source.source_id.value, source.source_sha256, payload_sha)
    require((lineage.preview_id, lineage.company_id, lineage.income_year, lineage.source_id,
             lineage.source_sha256, lineage.payload_sha256) == expected)
    require((bridge.preview_id, bridge.company_id, bridge.income_year, bridge.source_id,
             bridge.source_sha256, bridge.payload_sha256) == expected)
    require(source.company_id == query.company_id and source.income_year == query.income_year)
    require(approval.id == lineage.approval_id and approval.preview_id == lineage.preview_id
            and approval.user_id == approval.approved_by == lineage.approved_by
            and approval.manifest_hash == lineage.manifest_sha256
            and approval.payload_hash == payload_sha
            and approval.adapter_version == 'rf1086-source-production-v1')
    review = approval.manifest['review']
    require(review['sha256'] == lineage.review_sha256)
    _validate_retained_source_review(lineage, approval, bridge, review, require)
    prior = approval.manifest['predecessor']
    predecessor = None if prior is None else rf.Rf1086SourceCorrectionPredecessor(
        rf.SubmissionId(prior['submissionId']), prior['manifestSha256'], prior['reason'])
    basis = rf.Rf1086SourceApprovalManifestBasis(source, preview,
        ActorId(ActorKind.USER, UserId(approval.user_id)), approval.entitlement_id,
        lineage.review_sha256, tuple(review['acknowledgedWarningCodes']), predecessor)
    rebuilt = rf.build_rf1086_source_approval_manifest(basis)
    require(rebuilt.manifest_sha256 == approval.manifest_hash
            and rebuilt.manifest == approval.manifest
            and rf.serialize_rf1086_source_approval_manifest(rebuilt) == lineage.manifest_text)
    require(projection.source == 'rf1086-full-year-v1' and projection.setup_id is None
            and projection.status == preview.readiness_status
            and projection.issues == preview.readiness_issues
            and projection.preview == preview.preview_text
            and projection.hovedskjema_xml == preview.hovedskjema_xml
            and projection.underskjema_xml == rebuilt.underskjema_xml)


def _validate_retained_source_review(lineage, approval, bridge, manifest_review, require):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value)
            value[key] = item
        return value

    require(type(lineage.review_text) is str and _sha256(lineage.review_text) == lineage.review_sha256)
    review = json.loads(lineage.review_text, object_pairs_hook=unique)
    require(isinstance(review, dict) and set(review) == {'version', 'binding', 'scope', 'comments',
            'overrides', 'permission', 'pilot', 'request', 'storedReleaseReady', 'technicalReleaseReady'})
    require(review['version'] == 'rf1086-source-review-v1'
            and review['storedReleaseReady'] is True and review['technicalReleaseReady'] is True)
    require(review['scope'] == {'companyId': lineage.company_id, 'incomeYear': lineage.income_year,
            'previewId': lineage.preview_id, 'sourceId': lineage.source_id,
            'sourceSha256': lineage.source_sha256, 'entitlementId': approval.entitlement_id,
            'warningCodes': list(manifest_review['acknowledgedWarningCodes']), 'blockers': []})
    binding = review['binding']
    require(isinstance(binding, dict) and set(binding) == {'preview_id', 'company_id', 'income_year',
            'source_id', 'source_sha256', 'payload_sha256', 'created_by', 'created_at'})
    require(all(binding[name] == getattr(bridge, name) for name in binding if name != 'created_at'))
    require(datetime.fromisoformat(binding['created_at']) == datetime.fromisoformat(bridge.created_at))
    permission, pilot, request = review['permission'], review['pilot'], review['request']
    require(isinstance(permission, dict) and isinstance(pilot, dict) and isinstance(request, dict))
    require(permission['company_id'] == lineage.company_id
            and permission['obligation'] == 'aksjonaerregisteroppgaven'
            and permission['submitter_user_id'] == permission['confirmed_by'] == approval.user_id
            and permission['production_enabled'] is True)
    require(pilot['id'] == approval.entitlement_id and pilot['company_id'] == lineage.company_id
            and pilot['income_year'] == lineage.income_year and pilot['user_id'] == approval.user_id
            and pilot['obligation'] == 'aksjonaerregisteroppgaven'
            and pilot['case_profile'] == 'rf1086_full_year_v1' and pilot['status'] == 'active')
    require(request['id'] == pilot['system_user_request_id']
            and request['company_id'] == lineage.company_id
            and request['initiating_owner_user_id'] == approval.user_id
            and request['obligation'] == 'aksjonaerregisteroppgaven' and request['status'] == 'accepted'
            and request['preflight_verified_at'] is not None
            and request['external_ref'] == pilot['system_user_external_reference'])
    for key in ('comments', 'overrides'):
        rows = review[key]
        require(type(rows) is list and all(isinstance(row, dict) for row in rows)
                and len({row['id'] for row in rows}) == len(rows)
                and [row['id'] for row in rows] == sorted(row['id'] for row in rows))
        require(all(row['company_id'] == lineage.company_id for row in rows))
    require(all(row['preview_id'] == lineage.preview_id
                and (row['severity'] != 'hard_block' or row['acknowledged_at'] is not None)
                for row in review['comments']))
    require(all(row['income_year'] == lineage.income_year and row['risk_level'] != 'block'
                for row in review['overrides']))


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

    async def generate_source_preview(self, command: GenerateRf1086SourcePreview) -> Rf1086SourcePreview:
        from .source_preview import prepare
        prepared = prepare(command)
        return await self._persistence.capture_source_preview(command, prepared)

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
        if (basis.preview.source == 'rf1086-full-year-v1' or basis.preview.id != str(command.preview_id)
                or basis.preview.status != 'ready' or not basis.preview.hovedskjema_xml):
            raise ShareholderRegisterFilingError.company_year_not_admitted()
        preview = _production_preview(basis.preview)
        manifest = rf1086_current_manifest(preview,actor_id=str(command.actor_id.subject),organization_number=basis.organization_number)
        digest = rf1086_current_manifest_hash(preview,actor_id=str(command.actor_id.subject),organization_number=basis.organization_number)
        from talli_backend.shared.kernel import CompanyId, IncomeYear
        return _recorded_result(await self._persistence.record_approval(command,Rf1086PreparedApproval(basis,manifest,digest)),
            company_id=CompanyId(basis.preview.company_id),income_year=IncomeYear(basis.preview.income_year))

    async def legacy_archive_source(self, query: Rf1086ArchiveQuery):
        return _validate_archive_source(query, await self._persistence.legacy_archive_source(query), include_production=False)

    async def archive_source(self, query: Rf1086ArchiveQuery):
        return _validate_archive_source(query,await self._persistence.archive_source(query))

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
