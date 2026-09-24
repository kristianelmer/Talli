"""Authenticated RF source capture and preview from public owner evidence.

This workflow constructs trusted context; callers cannot supply it. Documents
I/O and Governance's coherent read precede the short RF capture transaction.
Capture retains those exact observations, not a cross-owner production lease.
"""
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
    Rf1086YearSourceId, Rf1086SourcePreview, GenerateRf1086SourcePreview, PreviewId,
    assert_rf1086_year_source_integrity, assert_rf1086_year_source_fresh,
    assert_rf1086_source_preview_matches, create_rf1086_preparation_service,
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
            final, groups = _dividend_originals(item, view.company_id)
            decision = item.decision
            for originals in groups:
                _require(any(str(artifact.document_id) in verified_by_id
                    and verified_by_id[str(artifact.document_id)].content_sha256 == artifact.content_sha256 for artifact in originals),
                    'rf1086_source_governance_signed_document_unverified')
            economics = _dividend_economics(item)
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


def _dividend_originals(item, company_id):
    _require(len(item.finalizations) == 1, 'rf1086_source_governance_receipt_invalid')
    final, decision = item.finalizations[0], item.decision
    _require(final.company_id == company_id and decision.company_id == company_id
             and final.decision_id == decision.decision_id and final.decision_hash == decision.decision_hash
             and bool(final.signed_artifact_hashes), 'rf1086_source_governance_receipt_invalid')
    _require({'dividend_board_proposal', 'dividend_general_meeting_minutes'} <= final.signed_artifact_hashes.keys(),
             'rf1086_source_governance_receipt_invalid')
    groups = []
    for kind, content_hash in final.signed_artifact_hashes.items():
        originals = tuple(artifact for artifact in item.artifacts
            if artifact.variant is CorporateArtifactVariant.SIGNED_OWNER_ATTESTED
            and artifact.artifact_kind.value == kind and artifact.content_sha256 == content_hash)
        _require(bool(originals), 'rf1086_source_governance_signed_document_unverified')
        groups.append(originals)
    return final, tuple(groups)


def _dividend_economics(item) -> dict:
    canonical = item.decision.canonical_input
    dividend, holders = canonical['dividend'], canonical['shareholders']
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
    return {'event_type': 'dividend', 'event_date': item.reporting_date.value.isoformat(),
            'amount': _ore(dividend['amountOre']), 'allocations': allocations}


def _capital_economics(original, event_type) -> dict:
    business = original.canonical_facts['businessFacts']
    result = {'event_type': event_type, 'event_date': original.event_date.value.isoformat()}
    if event_type == 'cash_issue':
        count = business['issued_share_count']
        _require(type(count) is int and count > 0, 'rf1086_source_governance_economics_invalid')
        result.update(nominal_increase=_nok(business['nominal_increase']),
                      share_premium=_nok(business['share_premium']), issued_share_count=count)
    elif event_type == 'loss_covering_reduction':
        result.update(nominal_reduction=_nok(business['nominal_reduction']),
            old_share_capital=_nok(business['old_share_capital']), new_share_capital=_nok(business['new_share_capital']))
    else:
        raise Rf1086YearSourceError('rf1086_source_governance_economics_invalid')
    return result


@dataclass(frozen=True, slots=True)
class SourceIntakeDocument:
    document_id: str
    content_sha256: str
    role: str
    source_income_year: int | None
    variant: str | None
    revision: int | None
    artifact_id: str | None = None
    supersedes_artifact_id: str | None = None


@dataclass(frozen=True, slots=True)
class SourceIntakeRegisterReference:
    observation_id: str
    revision: int
    fact_sha256: str


@dataclass(frozen=True, slots=True)
class SourceIntakeDividendAllocation:
    shareholder_id: str
    amount: str
    share_count_basis: int


@dataclass(frozen=True, slots=True)
class SourceIntakeDividendEconomics:
    amount: str
    allocations: tuple[SourceIntakeDividendAllocation, ...]


@dataclass(frozen=True, slots=True)
class SourceIntakeFinalization:
    receipt_id: str
    source_income_year: int
    decision_sha256: str
    signed_artifact_hashes: Mapping[str, str]
    original_document_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceIntakeDividend:
    decision_id: str
    decision_sha256: str
    source_income_year: int
    reporting_date: str
    reporting_year: int
    status: str
    supersedes_decision_id: str | None
    economics: SourceIntakeDividendEconomics | None
    finalizations: tuple[SourceIntakeFinalization, ...]
    documents: tuple[SourceIntakeDocument, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceIntakeCapitalEconomics:
    nominal_increase: str | None
    share_premium: str | None
    issued_share_count: int | None
    nominal_reduction: str | None
    old_share_capital: str | None
    new_share_capital: str | None


@dataclass(frozen=True, slots=True)
class SourceIntakeCapitalEvent:
    receipt_id: str
    event_reference: str
    event_kind: str
    phase: str
    source_income_year: int
    reporting_date: str
    reporting_year: int
    correction_of_event_id: str | None
    accounting_entry_id: str
    economics: SourceIntakeCapitalEconomics | None
    documents: tuple[SourceIntakeDocument, ...]
    register_observation: SourceIntakeRegisterReference | None
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceIntakeCapital:
    representative_receipt_id: str
    status: str
    events: tuple[SourceIntakeCapitalEvent, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceIntakeAmendment:
    original_entry_id: str
    reversal_entry_id: str
    replacement_entry_id: str | None
    source_income_year: int
    reason: str


@dataclass(frozen=True, slots=True)
class SourceIntakeCompany:
    org_number: str
    name: str
    address: str
    postal_code: str
    city: str
    identity_confirmed_at: str
    identity_locked_at: str


@dataclass(frozen=True, slots=True)
class SourceIntakeBasis:
    company_id: str
    income_year: int
    company: SourceIntakeCompany
    enumeration_sha256: str
    enumeration_complete: bool
    dividends: tuple[SourceIntakeDividend, ...]
    capital_events: tuple[SourceIntakeCapital, ...]
    ledger_amendments: tuple[SourceIntakeAmendment, ...]
    blockers: tuple[str, ...]


def _intake_projection(company, view) -> SourceIntakeBasis:
    """Retain every owner-enumerated row; parsing never certifies capture readiness."""
    dividends, capital = [], []
    for item in view.dividends:
        decision = item.decision
        _require(all(row.company_id == view.company_id for row in
            (decision, *item.document_sets, *item.artifacts, *item.events, *item.finalizations)),
            'rf1086_source_governance_scope_mismatch')
        blockers = []
        if item.status != 'finalized' or item.reporting_date.value.year != int(view.income_year):
            blockers.append('rf1086_source_governance_unresolved')
        if len(item.finalizations) != 1:
            blockers.append('rf1086_source_governance_receipt_invalid')
        economics = None
        try:
            facts = _dividend_economics(item)
            economics = SourceIntakeDividendEconomics(format(facts['amount'], 'f'), tuple(
                SourceIntakeDividendAllocation(holder, format(amount, 'f'), count)
                for holder, amount, count in facts['allocations']))
        except (KeyError, TypeError, ValueError, AttributeError):
            blockers.append('rf1086_source_governance_economics_invalid')
        documents = tuple(SourceIntakeDocument(str(row.document_id), row.content_sha256,
            row.artifact_kind.value, int(row.income_year), row.variant.value, None,
            str(row.artifact_id), str(row.supersedes_artifact_id) if row.supersedes_artifact_id else None)
            for row in item.artifacts)
        original_ids = ()
        if item.finalizations:
            try:
                _, groups = _dividend_originals(item, view.company_id)
                original_ids = tuple(sorted({str(original.document_id) for group in groups for original in group}))
            except Rf1086YearSourceError as error:
                blockers.append(str(error))
        finals = tuple(SourceIntakeFinalization(str(row.finalization_id), int(row.income_year),
            row.decision_hash, row.signed_artifact_hashes, original_ids) for row in item.finalizations)
        dividends.append(SourceIntakeDividend(str(decision.decision_id), decision.decision_hash,
            int(decision.income_year), item.reporting_date.value.isoformat(), item.reporting_date.value.year,
            item.status, str(decision.supersedes_decision_id) if decision.supersedes_decision_id else None,
            economics, finals, documents, tuple(dict.fromkeys(blockers))))
    for item in view.supported_events:
        rows = item.lifecycle_events or (item.recorded,)
        _require(item.recorded in rows and all(row.event.company_id == view.company_id for row in rows),
                 'rf1086_source_governance_scope_mismatch')
        events = []
        for row in rows:
            original = row.event
            blockers = []
            economics = None
            event_type = {'cash_capital_increase': 'cash_issue',
                'loss_coverage_capital_reduction': 'loss_covering_reduction'}.get(original.event_kind.value)
            try:
                values = _capital_economics(original, event_type)
                economics = SourceIntakeCapitalEconomics(**{name:
                    format(values[name], 'f') if isinstance(values.get(name), Decimal) else values.get(name)
                    for name in SourceIntakeCapitalEconomics.__dataclass_fields__})
            except (KeyError, TypeError, ValueError, AttributeError):
                blockers.append('rf1086_source_governance_economics_invalid')
            documents, reference = [], None
            try:
                for fact in original.canonical_facts['documentFacts']:
                    documents.append(SourceIntakeDocument(_reference(fact['document_id']), fact['content_sha256'],
                        fact['evidence_kind'], None, None, fact['revision']))
                fact = original.canonical_facts.get('shareholderRegisterFact')
                if fact is not None:
                    reference = SourceIntakeRegisterReference(_reference(fact['record_id']), fact['revision'], fact['fact_sha256'])
            except (KeyError, TypeError, ValueError, AttributeError):
                # Never label a partially decoded reference set as complete.
                raise Rf1086YearSourceError('rf1086_source_governance_receipt_invalid') from None
            if not documents:
                blockers.append('rf1086_source_governance_signed_document_unverified')
            if original.phase.value in {'registered', 'first_recognized_after_registration'} and reference is None:
                blockers.append('rf1086_source_independent_register_unavailable')
            events.append(SourceIntakeCapitalEvent(str(original.event_id), str(original.event_reference),
                original.event_kind.value, original.phase.value, int(original.income_year),
                original.event_date.value.isoformat(), original.event_date.value.year,
                str(row.correction_of_event_id) if row.correction_of_event_id else None, str(row.accounting_entry_id),
                economics, tuple(documents), reference, tuple(blockers)))
        representative = item.recorded
        blockers = []
        if (item.status != 'recorded' or representative.correction_of_event_id is not None
                or representative.event.phase.value not in {'registered', 'first_recognized_after_registration'}
                or representative.event.income_year != view.income_year):
            blockers.append('rf1086_source_governance_unresolved')
        capital.append(SourceIntakeCapital(str(representative.event.event_id), item.status, tuple(events), tuple(blockers)))
    _require(all(row.company_id == view.company_id for row in view.ledger_amendments),
             'rf1086_source_governance_scope_mismatch')
    amendments = tuple(SourceIntakeAmendment(str(row.original_entry_id), str(row.reversal_entry_id),
        str(row.replacement_entry_id) if row.replacement_entry_id else None, int(row.income_year), row.reason)
        for row in view.ledger_amendments)
    blockers = tuple(sorted({code for item in (*dividends, *capital) for code in item.blockers}
        | {code for item in capital for event in item.events for code in event.blockers}
        | ({'rf1086_source_governance_unresolved'} if amendments else set())))
    return SourceIntakeBasis(company.id, int(view.income_year), SourceIntakeCompany(company.org_number, company.name,
        company.address, company.postal_code, company.city, company.identity_confirmed_at, company.identity_locked_at), view.enumeration_sha256,
        True, tuple(dividends), tuple(capital), amendments, blockers)


class ShareholderRegisterSourceWorkflow:
    def __init__(self, rf_sessions: ShareholderRegisterFilingSessionFactory,
            company_access: CompanyAccessService, documents: DocumentsSessionFactory,
            governance: GovernanceReportingYearReader) -> None:
        self._rf_sessions = rf_sessions
        self._company_access = company_access
        self._documents = documents
        self._governance = governance

    async def read_source_intake_basis(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, correlation_id: CorrelationId) -> SourceIntakeBasis:
        """Owner-only discovery; original bytes and capture authority are not verified here."""
        await self._rf_sessions.session(access_token)
        company = (await self._company_access.company_record(access_token, company_id=str(company_id))).company
        _require(company.id == str(company_id) and company.role == 'owner' and company.entity_type == 'AS'
                 and company.identity_confirmed_at is not None and company.identity_locked_at is not None,
                 'rf1086_source_owner_required')
        view = await self._governance.read_reporting_year_evidence(access_token,
            company_id=company_id, income_year=income_year, correlation_id=correlation_id)
        _require(view.company_id == company_id and view.income_year == income_year,
                 'rf1086_source_governance_scope_mismatch')
        return _intake_projection(company, view)

    async def read_source_document(self, access_token: str, *, company_id: CompanyId,
            document_id: DocumentId) -> Rf1086YearDocumentEvidence:
        """Read verified source metadata for the current accepted AS owner.

        This observation preserves the original document year and is not capture
        authority: capture verifies the bytes and metadata again.
        """
        session = await self._rf_sessions.session(access_token)
        company = (await self._company_access.company_record(access_token, company_id=str(company_id))).company
        _require(company.id == str(company_id) and company.role == 'owner' and company.entity_type == 'AS'
                 and company.identity_confirmed_at is not None and company.identity_locked_at is not None,
                 'rf1086_source_owner_required')
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id, 'rf1086_source_owner_required')
        evidence = await documents.verify_document_evidence(document_id)
        _require(evidence.document.company_id == company_id and evidence.document.document_id == document_id,
                 'rf1086_source_document_not_found')
        return _document_projection(evidence)

    async def read_current_year_source(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear) -> Rf1086YearSourceSnapshot | None:
        """Read retained facts for correction, without certifying current evidence.

        Original bytes may have changed since capture. They are deliberately not
        read here; a subsequent capture independently verifies all owner evidence.
        """
        session = await self._rf_sessions.session(access_token)
        company = (await self._company_access.company_record(access_token, company_id=str(company_id))).company
        _require(company.id == str(company_id) and company.role == 'owner' and company.entity_type == 'AS'
                 and company.identity_confirmed_at is not None and company.identity_locked_at is not None,
                 'rf1086_source_owner_required')
        source = await session.read_current_year_source(Rf1086SourceQuery(company_id, income_year, session.actor_id))
        if source is None:
            return None
        assert_rf1086_year_source_integrity(source)
        _require(source.company_id == company_id and source.income_year == income_year,
                 'rf1086_source_company_year_mismatch')
        # A rename, address update, or renewed confirmation must not hide the
        # retained facts needed to correct them. Company ID and organization
        # number anchor identity; capture checks the complete current projection.
        _require(source.command.case.company.org_number == company.org_number,
                 'rf1086_source_company_year_mismatch')
        return source

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
            economics = _capital_economics(original, event.type)
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
                Rf1086SourceQuery(command.company_id, command.income_year, session.actor_id), observation_id)
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
        context = await self._verify_year_source_context(access_token, session, command, correlation_id=correlation_id)
        return await session.record_year_source(command, context=context, idempotency_key=idempotency_key)

    async def _fresh_source(self, access_token: str, session: AuthenticatedShareholderRegisterFilingSession, *,
            company_id: CompanyId, income_year: IncomeYear, source_id: Rf1086YearSourceId,
            correlation_id: CorrelationId) -> Rf1086YearSourceSnapshot:
        query = Rf1086SourceQuery(company_id, income_year, session.actor_id)
        source = await session.read_year_source(query, source_id)
        _require(source is not None, 'rf1086_source_not_found')
        assert_rf1086_year_source_integrity(source)
        _require(source.source_id == source_id and source.company_id == company_id
                 and source.income_year == income_year, 'rf1086_source_company_year_mismatch')
        context = await self._verify_year_source_context(access_token, session, source.command,
                                                         correlation_id=correlation_id)
        current = await session.read_current_year_source(query)
        _require(current is not None, 'rf1086_source_changed')
        assert_rf1086_year_source_integrity(current)
        assert_rf1086_year_source_fresh(source, current_source_id=current.source_id,
            current_source_sha256=current.source_sha256, context=context)
        return source

    async def generate_source_preview(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, source_id: Rf1086YearSourceId,
            correlation_id: CorrelationId) -> Rf1086SourcePreview:
        session = await self._rf_sessions.session(access_token)
        source = await self._fresh_source(access_token, session, company_id=company_id,
            income_year=income_year, source_id=source_id, correlation_id=correlation_id)
        # Persistence rechecks the current source under the RF company/year lock
        # before append, covering supersession after these external owner reads.
        preview = await create_rf1086_preparation_service(session).generate_source_preview(
            GenerateRf1086SourcePreview(company_id=company_id, income_year=income_year, source=source))
        assert_rf1086_source_preview_matches(preview, source)
        return preview

    async def read_source_preview(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: PreviewId,
            correlation_id: CorrelationId) -> Rf1086SourcePreview:
        """Fresh owner review of a retained preview, without creating evidence.

        This is a point-in-time review read, not a production authorization or
        historical archive endpoint. Source corrections and changed originals
        must be reviewed through a newly captured source.
        """
        session = await self._rf_sessions.session(access_token)
        preview = await session.source_preview(preview_id)
        _require(preview is not None and preview.preview_id == preview_id
                 and preview.company_id == company_id and preview.income_year == income_year,
                 'rf1086_source_preview_not_found')
        source = await self._fresh_source(access_token, session, company_id=company_id,
            income_year=income_year, source_id=preview.source_id, correlation_id=correlation_id)
        assert_rf1086_source_preview_matches(preview, source)
        return preview

    async def _verify_year_source_context(self, access_token: str,
            session: AuthenticatedShareholderRegisterFilingSession, command: RecordRf1086YearSource, *,
            correlation_id: CorrelationId) -> Rf1086VerifiedYearSourceContext:
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
        return Rf1086VerifiedYearSourceContext(
            actor_id=session.actor_id, accepted_owner=True, company_id=command.company_id,
            income_year=command.income_year, company=current_company,
            company_identity_sha256=rf1086_year_source_digest({
                'company_id': company.id, 'company': current_company, 'entity_type': company.entity_type,
                'identity_confirmed_at': company.identity_confirmed_at, 'identity_locked_at': company.identity_locked_at,
            }), documents=tuple(verified), governance_receipts=receipts,
            complete_governance_enumeration=True, governance_enumeration_sha256=view.enumeration_sha256,
        )
