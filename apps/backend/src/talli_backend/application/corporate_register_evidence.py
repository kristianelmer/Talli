"""Point-in-time RF evidence binding for registered Governance capital events.

Only owner public contracts are used. RF currentness and Documents verification
use separate transactions: this is not a cross-owner freshness lease. Original
byte I/O must move before any future company-guard transaction; only retained
receipt assertions may run while that shared guard is held.
"""
from __future__ import annotations

from decimal import Decimal, localcontext

from talli_backend.application.shareholder_register_filing_session import (
    ShareholderRegisterFilingAuthenticationError,
    ShareholderRegisterFilingSessionFactory,
)
from talli_backend.modules.corporate_governance.public import (
    CashCapitalIncreaseEventFacts,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    LossCoverageCapitalReductionEventFacts,
    RecordSupportedCorporateEventCommand,
    SupportedCorporateEventKind,
    SupportedCorporateEventPhase,
)
from talli_backend.modules.documents.public import (
    DocumentId, DocumentStatus, DocumentsSessionFactory, document_metadata_sha256,
)
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086ProductionError, Rf1086RegisterObservationError,
    Rf1086RegisterObservationId, Rf1086RegisterObservationSnapshot,
    Rf1086SourceQuery, assert_rf1086_register_observation_integrity,
)
from talli_backend.shared.kernel import DomainError, ErrorCategory


def requires_register_observation(command: RecordSupportedCorporateEventCommand) -> bool:
    return (
        command.event_kind is SupportedCorporateEventKind.CASH_CAPITAL_INCREASE
        and command.phase is SupportedCorporateEventPhase.REGISTERED
    ) or (
        command.event_kind is SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION
        and command.phase in {
            SupportedCorporateEventPhase.REGISTERED,
            SupportedCorporateEventPhase.FIRST_RECOGNIZED_AFTER_REGISTRATION,
        }
    )


def _require(condition: bool) -> None:
    if not condition:
        raise CorporateGovernanceError.precondition(
            CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE,
            "The current independent shareholder-register observation does not match the event evidence.",
        )


def _difference_equals(after: Decimal, before: Decimal, expected: Decimal) -> bool:
    # Avoid rounding large, otherwise valid exact decimal facts in default context.
    with localcontext() as context:
        context.prec = max(28, sum(len(v.as_tuple().digits) + abs(v.as_tuple().exponent)
                                   for v in (after, before, expected)) + 2)
        return after - before == expected


class CorporateRegisterEvidenceVerifier:
    def __init__(self, rf_sessions: ShareholderRegisterFilingSessionFactory,
                 documents: DocumentsSessionFactory) -> None:
        self._rf_sessions = rf_sessions
        self._documents = documents

    async def verify(self, access_token: str,
                     command: RecordSupportedCorporateEventCommand) -> Rf1086RegisterObservationSnapshot:
        try:
            return await self._verify(access_token, command)
        except CorporateGovernanceError:
            raise
        except ShareholderRegisterFilingAuthenticationError:
            raise CorporateGovernanceError.forbidden() from None
        except DomainError as error:
            if error.category is ErrorCategory.FORBIDDEN:
                raise CorporateGovernanceError.forbidden() from None
            if error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE:
                raise CorporateGovernanceError.unavailable() from None
            raise CorporateGovernanceError.precondition(
                CorporateGovernanceErrorCode.CORPORATE_EVENT_EVIDENCE_INCOMPLETE,
                "Independent shareholder-register evidence could not be verified.",
            ) from None
        except (Rf1086RegisterObservationError, Rf1086ProductionError):
            raise CorporateGovernanceError.unavailable() from None

    async def _verify(self, access_token: str,
                      command: RecordSupportedCorporateEventCommand) -> Rf1086RegisterObservationSnapshot:
        _require(requires_register_observation(command))
        reference = command.shareholder_register_fact
        _require(reference is not None)
        rf = await self._rf_sessions.session(access_token)
        documents = await self._documents.session(access_token)
        if rf.actor_id != command.actor_id or documents.actor_id != command.actor_id:
            raise CorporateGovernanceError.forbidden()
        snapshot = await rf.read_current_register_observation(
            Rf1086SourceQuery(command.company_id, command.income_year, command.actor_id),
            Rf1086RegisterObservationId(str(reference.record_id)),
        )
        _require(snapshot is not None)
        assert_rf1086_register_observation_integrity(snapshot)
        observation = snapshot.command
        _require(type(reference.revision) is int
                 and (snapshot.observation_id.value, snapshot.version, snapshot.fact_sha256)
                 == (str(reference.record_id), reference.revision, reference.fact_sha256))
        _require(observation.company_id == command.company_id
                 and observation.income_year == command.income_year
                 and observation.effective_at.date() == command.event_date.value)
        before, after, facts = observation.before, observation.after, command.facts
        if isinstance(facts, CashCapitalIncreaseEventFacts):
            _require(observation.event_kind == "cash_issue"
                     and after.share_count - before.share_count == facts.issued_share_count
                     and after.nominal_value == before.nominal_value
                     and _difference_equals(after.share_capital, before.share_capital, facts.nominal_increase.amount))
            # The register has no premium field. Existing Governance payment
            # validation and later full RF reconciliation retain that check.
        elif isinstance(facts, LossCoverageCapitalReductionEventFacts):
            _require(observation.event_kind == "loss_covering_reduction"
                     and before.share_capital == facts.old_share_capital.amount
                     and after.share_capital == facts.new_share_capital.amount
                     and _difference_equals(before.share_capital, after.share_capital, facts.nominal_reduction.amount))
        else:
            _require(False)

        originals = {}
        for expected in observation.documents:
            if expected.document_id not in originals:
                originals[expected.document_id] = await documents.verify_document_evidence(DocumentId(expected.document_id))
            evidence = originals[expected.document_id]
            record, retained = evidence.document, evidence.retained_original
            _require(record.document_id == DocumentId(expected.document_id)
                     and record.company_id == command.company_id
                     and record.status is DocumentStatus.ATTACHED and record.linked_to == "workspace"
                     and record.document_type in {"corporate_document", "accounting_document"}
                     and record.income_year == expected.source_income_year
                     and record.content_sha256 == evidence.content_sha256 == expected.content_sha256 == expected.content_version_sha256
                     and record.byte_length == evidence.byte_length == expected.byte_length
                     and record.status == evidence.integrity_status
                     and record.status.value == expected.integrity_status
                     and record.document_type == expected.document_type
                     and record.created_at == expected.created_at
                     and document_metadata_sha256(record) == expected.metadata_sha256)
            _require(retained is not None and retained.document_id == record.document_id
                     and retained.company_id == record.company_id and retained.source_income_year == record.income_year
                     and retained.metadata_sha256 == expected.metadata_sha256
                     and retained.content_sha256 == expected.content_sha256 and retained.byte_length == expected.byte_length)
        return snapshot
