"""Authenticated RF source capture from public owner evidence.

This workflow constructs trusted context; callers cannot supply it. Documents
I/O and Governance's coherent read precede the short RF capture transaction.
Capture retains those exact observations, not a cross-owner production lease.
"""
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Protocol

from talli_backend.application.shareholder_register_filing_session import (
    AuthenticatedShareholderRegisterFilingSession, ShareholderRegisterFilingSessionFactory,
)
from talli_backend.modules.company_access.public import CompanyAccessService
from talli_backend.modules.corporate_governance.public import CorporateArtifactVariant, CorporateGovernanceYearEvidence
from talli_backend.modules.documents.public import (
    DocumentId, DocumentStatus, DocumentsSessionFactory, VerifiedDocumentEvidence, document_metadata_sha256,
)
from talli_backend.modules.shareholder_register_filing.public import (
    RecordRf1086YearSource, Rf1086VerifiedYearSourceContext, Rf1086YearDocumentEvidence,
    Rf1086YearGovernanceReceipt, Rf1086YearSourceError, Rf1086YearSourceSnapshot,
    rf1086_year_source_digest,
    RecordRf1086RegisterObservation, Rf1086RegisterDocumentEvidence,
    Rf1086RegisterObservationSnapshot, Rf1086VerifiedRegisterObservationContext,
    Rf1086SourceQuery, Rf1086RegisterObservationId, Rf1086RegisterObservationMatchQuery,
    verify_rf1086_register_observation, rf1086_event_register_states,
)
from talli_backend.shared.kernel import CompanyId, CorrelationId, IdempotencyKey, IncomeYear


class GovernanceReportingYearReader(Protocol):
    async def read_reporting_year_evidence(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, correlation_id: CorrelationId) -> CorporateGovernanceYearEvidence: ...


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise Rf1086YearSourceError(code)


def _ore(value: object) -> Decimal:
    _require(type(value) is int and value > 0, 'rf1086_source_governance_economics_invalid')
    return Decimal((0, tuple(int(digit) for digit in str(value)), -2))


def _document_projection(evidence: VerifiedDocumentEvidence) -> Rf1086YearDocumentEvidence:
    record = evidence.document
    _require(evidence.content_sha256 == record.content_sha256 and evidence.byte_length == record.byte_length
             and evidence.integrity_status == record.status and isinstance(record.income_year, IncomeYear),
             'rf1086_source_documents_unverified')
    return Rf1086YearDocumentEvidence(
        document_id=str(record.document_id), company_id=record.company_id,
        content_version_sha256=evidence.content_sha256, content_sha256=evidence.content_sha256,
        document_type=record.document_type, integrity_status=evidence.integrity_status.value,
        byte_length=evidence.byte_length, created_at=record.created_at,
        metadata_sha256=document_metadata_sha256(record), source_income_year=record.income_year,
    )


def _dividend_receipts(view: CorporateGovernanceYearEvidence, verified_documents: tuple[Rf1086YearDocumentEvidence, ...]) -> tuple[Rf1086YearGovernanceReceipt, ...]:
    # Original supersession/reversal history is a blocker until correction
    # admission is implemented; it cannot vanish into an apparently empty year.
    _require(not view.ledger_amendments and all(item.status == 'finalized' for item in view.dividends),
             'rf1086_source_governance_unresolved')
    receipts = []
    verified_by_id = {item.document_id: item for item in verified_documents}
    try:
        for item in view.dividends:
            _require(item.reporting_date.value.year == int(view.income_year),
                     'rf1086_source_governance_unresolved')
            _require(len(item.finalizations) == 1, 'rf1086_source_governance_receipt_invalid')
            final = item.finalizations[0]
            decision = item.decision
            _require(final.company_id == view.company_id and decision.company_id == view.company_id
                     and final.decision_id == decision.decision_id and final.decision_hash == decision.decision_hash
                     and bool(final.signed_artifact_hashes), 'rf1086_source_governance_receipt_invalid')
            _require({'dividend_board_proposal', 'dividend_general_meeting_minutes'} <= final.signed_artifact_hashes.keys(),
                     'rf1086_source_governance_receipt_invalid')
            for kind, content_hash in final.signed_artifact_hashes.items():
                originals = [artifact for artifact in item.artifacts
                    if artifact.variant is CorporateArtifactVariant.SIGNED_OWNER_ATTESTED
                    and artifact.artifact_kind.value == kind and artifact.content_sha256 == content_hash]
                _require(any(str(artifact.document_id) in verified_by_id
                    and verified_by_id[str(artifact.document_id)].content_sha256 == content_hash for artifact in originals),
                    'rf1086_source_governance_signed_document_unverified')
            canonical = decision.canonical_input
            dividend = canonical['dividend']
            holders = canonical['shareholders']
            _require(isinstance(dividend, Mapping) and isinstance(holders, (tuple, list)),
                     'rf1086_source_governance_economics_invalid')
            counts = {holder['shareholderId']: holder['shareCount'] for holder in holders}
            _require(len(counts) == len(holders) and all(type(value) is int and value > 0 for value in counts.values()),
                     'rf1086_source_governance_economics_invalid')
            allocations = tuple(sorted(((row['shareholderId'], _ore(row['amountOre']), counts[row['shareholderId']])
                                        for row in dividend['allocations']), key=lambda row: row[0]))
            _require(len({row[0] for row in allocations}) == len(allocations)
                     and sum(row['amountOre'] for row in dividend['allocations']) == dividend['amountOre'],
                     'rf1086_source_governance_economics_invalid')
            economics = {'event_type': 'dividend', 'event_date': item.reporting_date.value.isoformat(),
                         'amount': _ore(dividend['amountOre']), 'allocations': allocations}
            # Preserve original Governance source-year and receipt fields in the
            # proof. Only RF's derived reportable year uses the meeting date.
            finalization_hash = rf1086_year_source_digest({
                'version': 'rf1086-governance-dividend-receipt-1', 'finalization': final,
                'decision_id': str(decision.decision_id), 'decision_hash': decision.decision_hash,
                'source_income_year': int(decision.income_year),
                'reporting_date': item.reporting_date.value.isoformat(),
            })
            receipts.append(Rf1086YearGovernanceReceipt(
                receipt_id=str(final.finalization_id), company_id=view.company_id,
                income_year=IncomeYear(item.reporting_date.value.year), event_type='dividend',
                economic_sha256=rf1086_year_source_digest(economics), finalization_sha256=finalization_hash,
                signed_document_hashes=tuple(sorted(final.signed_artifact_hashes.values())), active=True,
            ))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, Rf1086YearSourceError):
            raise
        raise Rf1086YearSourceError('rf1086_source_governance_receipt_invalid') from None
    return tuple(receipts)


def _reference(value: object) -> str:
    result = value.get('value') if isinstance(value, Mapping) else value
    _require(isinstance(result, str), 'rf1086_source_governance_receipt_invalid')
    return result


def _nok(value: object) -> Decimal:
    _require(isinstance(value, Mapping) and value.get('currency') == 'NOK' and isinstance(value.get('amount'), str),
             'rf1086_source_governance_economics_invalid')
    try:
        amount = Decimal(value['amount'])
    except (KeyError, TypeError, InvalidOperation):
        raise Rf1086YearSourceError('rf1086_source_governance_economics_invalid') from None
    _require(amount.is_finite() and amount >= 0, 'rf1086_source_governance_economics_invalid')
    return amount


class ShareholderRegisterSourceWorkflow:
    def __init__(self, rf_sessions: ShareholderRegisterFilingSessionFactory,
            company_access: CompanyAccessService, documents: DocumentsSessionFactory,
            governance: GovernanceReportingYearReader) -> None:
        self._rf_sessions = rf_sessions
        self._company_access = company_access
        self._documents = documents
        self._governance = governance

    async def _capital_receipts(self, session: AuthenticatedShareholderRegisterFilingSession,
            command: RecordRf1086YearSource, view: CorporateGovernanceYearEvidence,
            verified: tuple[Rf1086YearDocumentEvidence, ...]) -> tuple[Rf1086YearGovernanceReceipt, ...]:
        try:
            return await self._build_capital_receipts(session, command, view, verified)
        except (KeyError, TypeError, AttributeError, InvalidOperation):
            raise Rf1086YearSourceError('rf1086_source_governance_receipt_invalid') from None

    async def _build_capital_receipts(self, session: AuthenticatedShareholderRegisterFilingSession,
            command: RecordRf1086YearSource, view: CorporateGovernanceYearEvidence,
            verified: tuple[Rf1086YearDocumentEvidence, ...]) -> tuple[Rf1086YearGovernanceReceipt, ...]:
        receipts = []
        documents = {item.document_id: item for item in verified}
        by_receipt = {item.governance_receipt_id: item for item in command.event_evidence
                      if item.governance_receipt_id is not None}
        _require(not any(event.type == 'cash_nominal_increase' for event in command.case.events),
                 'rf1086_source_governance_nominal_increase_unavailable')
        for item in view.supported_events:
            recorded = item.recorded
            original = recorded.event
            _require(item.status == 'recorded' and recorded.correction_of_event_id is None,
                     'rf1086_source_governance_unresolved')
            _require(original.phase.value in {'registered', 'first_recognized_after_registration'},
                     'rf1086_source_governance_unresolved')
            evidence = by_receipt.get(str(original.event_id))
            _require(evidence is not None and 0 <= evidence.event_index < len(command.case.events),
                     'rf1086_source_governance_events_omitted')
            event = command.case.events[evidence.event_index]
            expected_kind = {'cash_issue': 'cash_capital_increase',
                             'loss_covering_reduction': 'loss_coverage_capital_reduction'}.get(event.type)
            _require(original.event_kind.value == expected_kind and original.company_id == command.company_id
                     and original.income_year == command.income_year and original.event_date.value == event.timestamp.date(),
                     'rf1086_source_governance_receipt_invalid')
            facts = original.canonical_facts
            business = facts['businessFacts']
            economics = {'event_type': event.type, 'event_date': original.event_date.value.isoformat()}
            if event.type == 'cash_issue':
                economics.update(nominal_increase=_nok(business['nominal_increase']),
                    share_premium=_nok(business['share_premium']), issued_share_count=business['issued_share_count'])
            else:
                economics.update(nominal_reduction=_nok(business['nominal_reduction']),
                    old_share_capital=_nok(business['old_share_capital']), new_share_capital=_nok(business['new_share_capital']))
            hashes = []
            for fact in facts['documentFacts']:
                document = documents.get(_reference(fact['document_id']))
                _require(document is not None and document.content_sha256 == fact['content_sha256'],
                         'rf1086_source_governance_signed_document_unverified')
                hashes.append(document.content_sha256)
            _require(bool(hashes), 'rf1086_source_governance_signed_document_unverified')
            reference = facts.get('shareholderRegisterFact')
            _require(isinstance(reference, Mapping), 'rf1086_source_independent_register_unavailable')
            observation_id = Rf1086RegisterObservationId(_reference(reference['record_id']))
            observation = await session.read_current_register_observation(
                Rf1086SourceQuery(command.company_id, command.income_year, command.actor_id), observation_id)
            _require(observation is not None, 'rf1086_source_independent_register_unavailable')
            _require(observation.confirmed_at <= recorded.recorded_at,
                     'rf1086_source_register_postdates_governance')
            before, after = rf1086_event_register_states(command.case, evidence.event_index)
            verify_rf1086_register_observation(observation, Rf1086RegisterObservationMatchQuery(
                observation_id, reference['revision'], reference['fact_sha256'], command.company_id,
                command.income_year, event.timestamp, event.type, before, after))
            for source in observation.command.documents:
                current = documents.get(source.document_id)
                _require(current is not None and current.company_id == source.company_id
                         and current.content_version_sha256 == source.content_version_sha256
                         and current.content_sha256 == source.content_sha256 and current.byte_length == source.byte_length
                         and current.document_type == source.document_type and current.integrity_status == source.integrity_status
                         and current.created_at == source.created_at and current.metadata_sha256 == source.metadata_sha256
                         and current.source_income_year == source.source_income_year,
                         'rf1086_source_register_original_changed')
            receipts.append(Rf1086YearGovernanceReceipt(receipt_id=str(original.event_id),
                company_id=command.company_id, income_year=command.income_year, event_type=event.type,
                economic_sha256=rf1086_year_source_digest(economics), finalization_sha256=recorded.finalization_sha256,
                signed_document_hashes=tuple(sorted(hashes)), active=True,
                register_observation_id=observation.observation_id.value, register_observation_sha256=observation.fact_sha256))
        _require(len(receipts) == sum(event.type in {'cash_issue', 'loss_covering_reduction'} for event in command.case.events),
                 'rf1086_source_independent_register_unavailable')
        return tuple(receipts)

    async def capture_register_observation(self, access_token: str,
            command: RecordRf1086RegisterObservation, *, idempotency_key: IdempotencyKey,
            correlation_id: CorrelationId) -> Rf1086RegisterObservationSnapshot:
        session = await self._rf_sessions.session(access_token)
        _require(session.actor_id == command.actor_id, 'rf1086_source_owner_required')
        company = (await self._company_access.company_record(access_token, company_id=str(command.company_id))).company
        _require(company.id == str(command.company_id) and company.role == 'owner' and company.entity_type == 'AS'
                 and company.identity_confirmed_at is not None and company.identity_locked_at is not None,
                 'rf1086_source_owner_required')
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id, 'rf1086_source_owner_required')
        verified = []
        originals = {}
        for expected in command.documents:
            if expected.document_id not in originals:
                originals[expected.document_id] = await documents.verify_document_evidence(DocumentId(expected.document_id))
            evidence = originals[expected.document_id]
            record = evidence.document
            _require(record.company_id == command.company_id and record.status is DocumentStatus.ATTACHED
                     and record.document_type in {'corporate_document', 'accounting_document'}
                     and record.linked_to == 'workspace', 'rf1086_source_register_original_required')
            # This proves the retained original bytes and owner-confirmed role;
            # it does not automatically extract or certify register contents.
            source = _document_projection(evidence)
            observed = Rf1086RegisterDocumentEvidence(
                document_id=source.document_id, company_id=source.company_id,
                content_version_sha256=source.content_version_sha256, content_sha256=source.content_sha256,
                byte_length=source.byte_length, document_type=source.document_type,
                integrity_status=source.integrity_status, created_at=source.created_at,
                metadata_sha256=source.metadata_sha256, role=expected.role,
                source_income_year=source.source_income_year,
            )
            _require(observed == expected, 'rf1086_source_documents_unverified')
            verified.append(observed)
        context = Rf1086VerifiedRegisterObservationContext(actor_id=session.actor_id, accepted_owner=True,
            company_id=command.company_id, income_year=command.income_year, documents=tuple(verified),
            independent_originals_verified=True)
        return await session.record_register_observation(command, context=context, idempotency_key=idempotency_key)

    async def capture_year_source(self, access_token: str, command: RecordRf1086YearSource, *,
            idempotency_key: IdempotencyKey, correlation_id: CorrelationId) -> Rf1086YearSourceSnapshot:
        session = await self._rf_sessions.session(access_token)
        _require(session.actor_id == command.actor_id, 'rf1086_source_owner_required')
        company = (await self._company_access.company_record(access_token, company_id=str(command.company_id))).company
        _require(company.id == str(command.company_id) and company.role == 'owner' and company.entity_type == 'AS'
                 and company.identity_confirmed_at is not None and company.identity_locked_at is not None,
                 'rf1086_source_owner_required')
        current_company = replace(command.case.company, org_number=company.org_number, name=company.name,
            address=company.address, postal_code=company.postal_code, city=company.city,
            income_year=int(command.income_year))
        _require(current_company == command.case.company, 'rf1086_source_company_year_mismatch')
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id, 'rf1086_source_owner_required')
        verified = []
        _require(bool(command.documents) and len({item.document_id for item in command.documents}) == len(command.documents),
                 'rf1086_source_documents_unverified')
        for expected in command.documents:
            evidence = await documents.verify_document_evidence(DocumentId(expected.document_id))
            observed = _document_projection(evidence)
            _require(observed == expected and observed.company_id == command.company_id,
                     'rf1086_source_documents_unverified')
            verified.append(observed)
        view = await self._governance.read_reporting_year_evidence(access_token,
            company_id=command.company_id, income_year=command.income_year, correlation_id=correlation_id)
        _require(view.company_id == command.company_id and view.income_year == command.income_year,
                 'rf1086_source_governance_scope_mismatch')
        receipts = _dividend_receipts(view, tuple(verified))
        receipts += await self._capital_receipts(session, command, view, tuple(verified))
        _require({item.receipt_id for item in receipts} == {item.governance_receipt_id for item in command.event_evidence
                  if item.governance_receipt_id is not None}, 'rf1086_source_governance_events_omitted')
        context = Rf1086VerifiedYearSourceContext(
            actor_id=session.actor_id, accepted_owner=True, company_id=command.company_id,
            income_year=command.income_year, company=current_company,
            company_identity_sha256=rf1086_year_source_digest({
                'company_id': company.id, 'company': current_company, 'entity_type': company.entity_type,
                'identity_confirmed_at': company.identity_confirmed_at, 'identity_locked_at': company.identity_locked_at,
            }), documents=tuple(verified), governance_receipts=receipts,
            complete_governance_enumeration=True, governance_enumeration_sha256=view.enumeration_sha256,
        )
        return await session.record_year_source(command, context=context, idempotency_key=idempotency_key)
