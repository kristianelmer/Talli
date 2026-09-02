"""Authenticated owner-dividend workflows and atomic capability composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from decimal import Decimal
from typing import Protocol

from talli_backend.application.annual_data_compatibility import (
    project_legacy_annual_basis,
)
from talli_backend.application.corporate_governance_session import (
    CorporateGovernanceSessionFactory,
    CorporateGovernanceWorkflowTransaction,
)
from talli_backend.modules.banking.public import (
    AccountingEntryReference as BankingAccountingEntryReference,
    BankTransactionId,
    ClaimBankTransactionForExternalActionCommand,
    ExternalActionReference,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    AnnualDataSourceFacts,
    AnnualCloseProposalCommand,
    AnnualCloseLifecycle,
    ApproveAnnualCloseCommand,
    AttestAnnualCloseSignedArtifactCommand,
    AttestOwnerDividendSignedArtifactCommand,
    ApproveOwnerDividendCommand,
    CorporateArtifactKind,
    CorporateDecisionKind,
    CorporateDecisionFactSources,
    CorporateDecisionId,
    CorporateDocumentReadiness,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateLifecycleSnapshot,
    CorporateAccountMovementFacts,
    CorporateReadinessSource,
    CorporateSourceReference,
    DerivedCorporateDecisionFacts,
    FinalizeOwnerDividendCommand,
    FinalizeAnnualCloseCommand,
    OwnerDividendLifecycle,
    OwnerDividendProposalCommand,
    PersistedCompanyFacts,
    PersistedShareholderFacts,
    ProposedAnnualClose,
    ProposedOwnerDividend,
    RecordShareholderLoanCommand,
    RecordAnnualCloseEventCommand,
    RecordOwnerDividendEventCommand,
    RecordOwnerDividendPaymentCommand,
    RecordedShareholderLoan,
    RegisterOwnerDividendDocumentsCommand,
    RegisterAnnualCloseDocumentsCommand,
    SHA256_PATTERN,
)
from talli_backend.modules.corporate_governance.service import (
    CorporateGovernanceService,
)
from talli_backend.modules.documents.public import (
    DocumentStatus,
    DocumentsSessionFactory,
)
from talli_backend.modules.ledger.public import (
    LedgerCommands,
    LedgerCursor,
    LedgerEntryId,
    LedgerPersistence,
    LedgerQueries,
    LedgerSourceRecordId,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
    PostShareholderLoanCommand,
    ShareholderLoanDirection as LedgerShareholderLoanDirection,
)
from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    IncomeYear,
    Money,
)


class CorporateGovernanceLedgerFacade(LedgerCommands, LedgerQueries, Protocol):
    pass


LedgerFacadeFactory = Callable[[LedgerPersistence], CorporateGovernanceLedgerFacade]
CompanyFactsReader = Callable[[str, CompanyId], Awaitable[PersistedCompanyFacts]]
_REQUIRED_ARTIFACT_KINDS = {
    CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
    CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
}
_REQUIRED_ANNUAL_ARTIFACT_KINDS = {
    CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
    CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,
}


def _money_from_ore(value: int) -> Money:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CorporateGovernanceError.unavailable()
    return Money.nok(Decimal(value) / Decimal(100))


class CorporateGovernanceApplication:
    def __init__(
        self,
        session_factory: CorporateGovernanceSessionFactory,
        documents_session_factory: DocumentsSessionFactory,
        ledger_facade_factory: LedgerFacadeFactory,
        company_facts_reader: CompanyFactsReader,
    ) -> None:
        self._session_factory = session_factory
        self._documents_session_factory = documents_session_factory
        self._ledger_facade_factory = ledger_facade_factory
        self._company_facts_reader = company_facts_reader
        self._service = CorporateGovernanceService()

    async def authenticated_actor_id(self, access_token: str) -> ActorId:
        """Resolve the verified actor without accepting an actor from transport input."""

        return (await self._session_factory.session(access_token)).actor_id

    async def list_lifecycle(
        self,
        access_token: str,
        company_ids: tuple[CompanyId, ...],
    ) -> CorporateLifecycleSnapshot:
        session = await self._session_factory.session(access_token)
        async with session.transaction() as transaction:
            return await transaction.list_lifecycle(company_ids)

    async def read_lifecycle(
        self,
        access_token: str,
        decision_id: CorporateDecisionId,
    ) -> CorporateLifecycleSnapshot:
        session = await self._session_factory.session(access_token)
        async with session.transaction() as transaction:
            return await transaction.read_lifecycle(decision_id)

    async def read_readiness(
        self,
        access_token: str,
        *,
        company_id: CompanyId,
        income_year: IncomeYear,
        decision_kind: CorporateDecisionKind,
        correlation_id: CorrelationId,
    ) -> CorporateDocumentReadiness:
        session = await self._session_factory.session(access_token)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, company_id)
            snapshot = await transaction.list_lifecycle((company_id,))
            facts = await self._derive_decision_facts_in_transaction(
                transaction,
                access_token=access_token,
                actor_id=session.actor_id,
                company_id=company_id,
                income_year=income_year,
                decision_kind=decision_kind,
                correlation_id=correlation_id,
            )
            current_source_hash = self._service.source_hash(
                CorporateReadinessSource(
                    source_id=facts.annual_basis.source_id,
                    annual_data_sha256=facts.annual_basis.annual_data_sha256,
                    annual_accounts_payload_sha256=(
                        facts.annual_basis.annual_accounts_payload_sha256
                    ),
                )
            )
            readiness = self._service.assess_lifecycle(
                snapshot,
                company_id=company_id,
                income_year=income_year,
                decision_kind=decision_kind,
                current_source_hash=current_source_hash,
            )
            decision = next(
                (
                    item
                    for item in snapshot.decisions
                    if item.decision_id == readiness.decision_id
                ),
                None,
            )
            if decision is not None and not self._service.current_facts_match(
                decision, facts
            ):
                readiness = self._service.assess_lifecycle(
                    snapshot,
                    company_id=company_id,
                    income_year=income_year,
                    decision_kind=decision_kind,
                    current_source_hash="0" * 64,
                )
            return readiness

    async def _session(self, access_token: str, actor_id):
        session = await self._session_factory.session(access_token)
        if session.actor_id != actor_id:
            raise CorporateGovernanceError.forbidden()
        return session

    @staticmethod
    async def _require_owner(
        transaction: CorporateGovernanceWorkflowTransaction,
        company_id,
    ) -> None:
        if await transaction.actor_role(company_id) != "owner":
            raise CorporateGovernanceError.forbidden()

    async def _derive_decision_facts_in_transaction(
        self,
        transaction: CorporateGovernanceWorkflowTransaction,
        *,
        access_token: str,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        decision_kind: CorporateDecisionKind,
        correlation_id: CorrelationId,
    ) -> DerivedCorporateDecisionFacts:
        company = await self._company_facts_reader(access_token, company_id)
        opening_snapshots = []
        opening_cursor = None
        while True:
            opening_page = await transaction.list_opening_snapshots(
                actor_id=actor_id,
                company_ids=(company_id,),
                correlation_id=correlation_id,
                cursor=opening_cursor,
                limit=100,
            )
            opening_snapshots.extend(opening_page.items)
            if not opening_page.has_more:
                break
            if opening_page.next_cursor is None:
                raise CorporateGovernanceError.unavailable()
            opening_cursor = opening_page.next_cursor
        opening = next(
            (
                item
                for item in opening_snapshots
                if item.company_id == company_id and item.income_year == income_year
            ),
            None,
        )
        if opening is None:
            raise CorporateGovernanceError.unavailable()
        annual_data = await transaction.list_annual_data_compatibility(
            company_id=company_id,
            income_year=(
                income_year
                if decision_kind is CorporateDecisionKind.ANNUAL_CLOSE
                else IncomeYear(int(income_year) - 1)
            ),
        )
        sources = CorporateDecisionFactSources(
            company=company,
            shareholders=tuple(
                PersistedShareholderFacts(
                    shareholder_id=item.shareholder_id,
                    name=item.name,
                    share_count=item.share_count,
                    order=index,
                )
                for index, item in enumerate(opening.shareholders)
            ),
            annual_data=tuple(
                AnnualDataSourceFacts(
                    source_id=CorporateSourceReference(item.source_id),
                    company_id=item.company_id,
                    income_year=item.income_year,
                    answers=item.answers,
                    confirmations=item.confirmations,
                    no_activity_confirmed=item.no_activity_confirmed,
                    annual_full_time_equivalents=(
                        item.annual_full_time_equivalents
                    ),
                    completed_at=item.completed_at,
                    updated_at=item.updated_at,
                )
                for item in annual_data
            ),
        )
        ledger = self._ledger_facade_factory(transaction)
        entries = []
        cursor: LedgerCursor | None = None
        while True:
            page = await ledger.list_entries(
                actor_id=actor_id,
                company_ids=(company_id,),
                correlation_id=correlation_id,
                cursor=cursor,
                limit=100,
            )
            entries.extend(page.items)
            if not page.page.has_more:
                break
            if page.page.next_cursor is None:
                raise CorporateGovernanceError.unavailable()
            cursor = page.page.next_cursor
        lines = tuple(
            CorporateAccountMovementFacts(
                income_year=entry.income_year,
                account=line.account,
                debit_ore=int(line.debit.amount * 100),
                credit_ore=int(line.credit.amount * 100),
            )
            for entry in entries
            for line in entry.lines
        )
        return self._service.derive_decision_facts(
            sources=sources,
            ledger_lines=lines,
            decision_kind=decision_kind,
            income_year=income_year,
            annual_basis_projector=project_legacy_annual_basis,
        )

    async def _require_current_decision_source(
        self,
        transaction: CorporateGovernanceWorkflowTransaction,
        *,
        access_token: str,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear | None,
        decision_kind: CorporateDecisionKind,
        decision_id: CorporateDecisionId,
        correlation_id: CorrelationId,
        snapshot: CorporateLifecycleSnapshot | None = None,
    ) -> None:
        if snapshot is None:
            snapshot = await transaction.read_lifecycle(decision_id)
        decision = next(
            (
                item
                for item in snapshot.decisions
                if item.decision_id == decision_id
                and item.company_id == company_id
                and item.decision_kind is decision_kind
            ),
            None,
        )
        if decision is None:
            raise CorporateGovernanceError.not_found()
        authoritative_income_year = decision.income_year
        if income_year is not None and income_year != authoritative_income_year:
            raise CorporateGovernanceError.not_found()
        facts = await self._derive_decision_facts_in_transaction(
            transaction,
            access_token=access_token,
            actor_id=actor_id,
            company_id=company_id,
            income_year=authoritative_income_year,
            decision_kind=decision_kind,
            correlation_id=correlation_id,
        )
        readiness = self._service.assess_lifecycle(
            snapshot,
            company_id=company_id,
            income_year=authoritative_income_year,
            decision_kind=decision_kind,
            current_source_hash=self._service.source_hash(
                CorporateReadinessSource(
                    source_id=facts.annual_basis.source_id,
                    annual_data_sha256=facts.annual_basis.annual_data_sha256,
                    annual_accounts_payload_sha256=(
                        facts.annual_basis.annual_accounts_payload_sha256
                    ),
                )
            ),
        )
        if (
            readiness.decision_id != decision_id
            or readiness.current_source_matches is not True
            or not self._service.current_facts_match(decision, facts)
        ):
            raise CorporateGovernanceError.precondition(
                CorporateGovernanceErrorCode.REVIEWED_FACTS_CHANGED,
                "The approved corporate decision is based on stale source facts.",
            )

    async def derive_decision_facts(
        self,
        access_token: str,
        *,
        company_id: CompanyId,
        income_year: IncomeYear,
        decision_kind: CorporateDecisionKind,
        correlation_id: CorrelationId,
    ) -> DerivedCorporateDecisionFacts:
        session = await self._session_factory.session(access_token)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, company_id)
            return await self._derive_decision_facts_in_transaction(
                transaction,
                access_token=access_token,
                actor_id=session.actor_id,
                company_id=company_id,
                income_year=income_year,
                decision_kind=decision_kind,
                correlation_id=correlation_id,
            )

    async def propose_owner_dividend(
        self,
        access_token: str,
        command: OwnerDividendProposalCommand,
    ) -> ProposedOwnerDividend:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            facts = await self._derive_decision_facts_in_transaction(
                transaction,
                access_token=access_token,
                actor_id=command.actor_id,
                company_id=command.company_id,
                income_year=command.income_year,
                decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
                correlation_id=command.correlation_id,
            )
            authoritative = replace(
                command,
                company=facts.company,
                shareholders=facts.shareholders,
                annual_basis=facts.annual_basis,
            )
            decision = self._service.build_owner_dividend_decision(authoritative)
            proposed = await transaction.propose_owner_dividend(
                authoritative,
                decision,
                self._service.canonical_payload(decision),
            )
        return ProposedOwnerDividend(
            decision=proposed.decision,
            state=proposed.state,
            replayed=proposed.replayed,
            artifacts=self._service.render_corporate_documents(proposed.decision),
        )

    async def propose_annual_close(
        self,
        access_token: str,
        command: AnnualCloseProposalCommand,
    ) -> ProposedAnnualClose:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            facts = await self._derive_decision_facts_in_transaction(
                transaction,
                access_token=access_token,
                actor_id=command.actor_id,
                company_id=command.company_id,
                income_year=command.income_year,
                decision_kind=CorporateDecisionKind.ANNUAL_CLOSE,
                correlation_id=command.correlation_id,
            )
            authoritative = replace(
                command,
                company=facts.company,
                shareholders=facts.shareholders,
                annual_basis=facts.annual_basis,
            )
            decision = self._service.build_annual_close_decision(authoritative)
            artifacts = self._service.render_corporate_documents(decision)
            proposed = await transaction.propose_annual_close(
                authoritative,
                decision,
                self._service.canonical_payload(decision),
                artifacts,
            )
        return ProposedAnnualClose(
            decision=proposed.decision,
            state=proposed.state,
            replayed=proposed.replayed,
            artifacts=artifacts,
        )

    async def register_owner_dividend_documents(
        self,
        access_token: str,
        command: RegisterOwnerDividendDocumentsCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        documents = await self._documents_session_factory.session(access_token)
        if documents.actor_id != command.actor_id:
            raise CorporateGovernanceError.forbidden()
        if (
            len(command.artifacts) != 2
            or {artifact.artifact_kind for artifact in command.artifacts}
            != _REQUIRED_ARTIFACT_KINDS
            or len({str(artifact.artifact_id) for artifact in command.artifacts}) != 2
            or len({str(artifact.document_id) for artifact in command.artifacts}) != 2
        ):
            raise CorporateGovernanceError.invalid(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Owner-dividend documents must contain the exact required artifacts.",
            )
        records = await documents.list_documents((command.company_id,))
        by_id = {str(record.document_id): record for record in records}
        for artifact in command.artifacts:
            record = by_id.get(str(artifact.document_id))
            if (
                record is None
                or record.company_id != command.company_id
                or record.linked_to != f"corporate_decision:{command.decision_id}"
                or record.status is not DocumentStatus.GENERATED_UNSIGNED
                or not SHA256_PATTERN.fullmatch(artifact.content_sha256)
                or record.content_sha256 != artifact.content_sha256
                or artifact.byte_length <= 0
                or record.byte_length != artifact.byte_length
            ):
                raise CorporateGovernanceError.precondition(
                    CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
                    "Document evidence does not match the owner-dividend proposal.",
                )
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.register_owner_dividend_documents(command)

    async def register_annual_close_documents(
        self,
        access_token: str,
        command: RegisterAnnualCloseDocumentsCommand,
    ) -> AnnualCloseLifecycle:
        session = await self._session(access_token, command.actor_id)
        documents = await self._documents_session_factory.session(access_token)
        if documents.actor_id != command.actor_id:
            raise CorporateGovernanceError.forbidden()
        if (
            len(command.artifacts) != 2
            or {artifact.artifact_kind for artifact in command.artifacts}
            != _REQUIRED_ANNUAL_ARTIFACT_KINDS
            or len({str(artifact.artifact_id) for artifact in command.artifacts}) != 2
            or len({str(artifact.document_id) for artifact in command.artifacts}) != 2
        ):
            raise CorporateGovernanceError.invalid(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Annual-close documents must contain the exact required artifacts.",
            )
        records = await documents.list_documents((command.company_id,))
        by_id = {str(record.document_id): record for record in records}
        for artifact in command.artifacts:
            record = by_id.get(str(artifact.document_id))
            if (
                record is None
                or record.company_id != command.company_id
                or record.linked_to != f"corporate_decision:{command.decision_id}"
                or record.status is not DocumentStatus.GENERATED_UNSIGNED
                or not SHA256_PATTERN.fullmatch(artifact.content_sha256)
                or record.content_sha256 != artifact.content_sha256
                or artifact.byte_length <= 0
                or record.byte_length != artifact.byte_length
            ):
                raise CorporateGovernanceError.precondition(
                    CorporateGovernanceErrorCode.INVALID_INPUT,
                    "Document evidence does not match the annual-close proposal.",
                )
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.register_annual_close_documents(command)

    async def approve_owner_dividend(
        self,
        access_token: str,
        command: ApproveOwnerDividendCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.approve_owner_dividend(command)

    async def approve_annual_close(
        self,
        access_token: str,
        command: ApproveAnnualCloseCommand,
    ) -> AnnualCloseLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.approve_annual_close(command)

    async def record_annual_close_event(
        self,
        access_token: str,
        command: RecordAnnualCloseEventCommand,
    ) -> AnnualCloseLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.record_annual_close_event(command)

    async def finalize_annual_close(
        self,
        access_token: str,
        command: FinalizeAnnualCloseCommand,
    ) -> AnnualCloseLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            snapshot = await transaction.read_lifecycle(command.decision_id)
            if any(
                item.decision_id == command.decision_id
                for item in snapshot.finalizations
            ):
                return await transaction.finalize_annual_close(command)
            await self._require_current_decision_source(
                transaction,
                access_token=access_token,
                actor_id=command.actor_id,
                company_id=command.company_id,
                income_year=None,
                decision_kind=CorporateDecisionKind.ANNUAL_CLOSE,
                decision_id=command.decision_id,
                correlation_id=command.correlation_id,
                snapshot=snapshot,
            )
            return await transaction.finalize_annual_close(command)

    async def attest_annual_close_signed_artifact(
        self,
        access_token: str,
        command: AttestAnnualCloseSignedArtifactCommand,
    ) -> AnnualCloseLifecycle:
        session = await self._session(access_token, command.actor_id)
        documents = await self._documents_session_factory.session(access_token)
        if documents.actor_id != command.actor_id:
            raise CorporateGovernanceError.forbidden()
        records = await documents.list_documents((command.company_id,))
        record = next(
            (
                item
                for item in records
                if str(item.document_id) == str(command.signed_document_id)
            ),
            None,
        )
        if (
            record is None
            or record.company_id != command.company_id
            or record.linked_to != f"corporate_decision:{command.decision_id}"
            or record.status is not DocumentStatus.SIGNED_OWNER_ATTESTED
            or not SHA256_PATTERN.fullmatch(command.content_sha256)
            or record.content_sha256 != command.content_sha256
            or record.byte_length != command.byte_length
            or command.artifact_kind not in _REQUIRED_ANNUAL_ARTIFACT_KINDS
        ):
            raise CorporateGovernanceError.precondition(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Signed annual-close evidence does not match the uploaded document.",
            )
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            snapshot = await transaction.read_lifecycle(command.decision_id)
            readiness = self._service.assess_lifecycle(
                snapshot,
                company_id=command.company_id,
                income_year=record.income_year,
                decision_kind=CorporateDecisionKind.ANNUAL_CLOSE,
            )
            signers = readiness.required_signers.get(command.artifact_kind.value)
            if not signers:
                raise CorporateGovernanceError.unavailable()
            return await transaction.attest_annual_close_signed_artifact(
                replace(command, signers=tuple(signers))
            )

    async def record_owner_dividend_event(
        self,
        access_token: str,
        command: RecordOwnerDividendEventCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            return await transaction.record_owner_dividend_event(command)

    async def attest_owner_dividend_signed_artifact(
        self,
        access_token: str,
        command: AttestOwnerDividendSignedArtifactCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        documents = await self._documents_session_factory.session(access_token)
        if documents.actor_id != command.actor_id:
            raise CorporateGovernanceError.forbidden()
        records = await documents.list_documents((command.company_id,))
        record = next(
            (
                item
                for item in records
                if str(item.document_id) == str(command.signed_document_id)
            ),
            None,
        )
        if (
            record is None
            or record.company_id != command.company_id
            or record.linked_to != f"corporate_decision:{command.decision_id}"
            or record.status is not DocumentStatus.SIGNED_OWNER_ATTESTED
            or not SHA256_PATTERN.fullmatch(command.content_sha256)
            or record.content_sha256 != command.content_sha256
            or record.byte_length != command.byte_length
            or command.artifact_kind not in _REQUIRED_ARTIFACT_KINDS
        ):
            raise CorporateGovernanceError.precondition(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Signed owner-dividend evidence does not match the uploaded document.",
            )
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            snapshot = await transaction.read_lifecycle(command.decision_id)
            readiness = self._service.assess_lifecycle(
                snapshot,
                company_id=command.company_id,
                income_year=record.income_year,
                decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            )
            signers = readiness.required_signers.get(command.artifact_kind.value)
            if not signers:
                raise CorporateGovernanceError.unavailable()
            return await transaction.attest_owner_dividend_signed_artifact(
                replace(command, signers=tuple(signers))
            )

    async def finalize_owner_dividend(
        self,
        access_token: str,
        command: FinalizeOwnerDividendCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            prepared = await transaction.prepare_owner_dividend_finalization(command)
            if prepared.replay is not None:
                return prepared.replay
            await self._require_current_decision_source(
                transaction,
                access_token=access_token,
                actor_id=command.actor_id,
                company_id=command.company_id,
                income_year=command.income_year,
                decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
                decision_id=command.decision_id,
                correlation_id=command.correlation_id,
            )
            ledger = self._ledger_facade_factory(transaction)
            posted = await ledger.post_owner_dividend_declared(
                PostOwnerDividendDeclaredCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    finalization_id=LedgerSourceRecordId(str(command.finalization_id)),
                    declared_amount=_money_from_ore(prepared.declared_amount_ore),
                    declaration_debit_account=prepared.declaration_debit_account,
                    dividend_payable_account=prepared.dividend_payable_account,
                    accounting_policy_version=prepared.accounting_policy_version,
                    ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
                )
            )
            if posted.entry_id != LedgerEntryId(str(command.ledger_entry_id)):
                raise CorporateGovernanceError.unavailable()
            return await transaction.complete_owner_dividend_finalization(
                command,
                AccountingEntryReference(str(posted.entry_id)),
                prepared,
            )

    async def record_owner_dividend_payment(
        self,
        access_token: str,
        command: RecordOwnerDividendPaymentCommand,
    ) -> OwnerDividendLifecycle:
        session = await self._session(access_token, command.actor_id)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            prepared = await transaction.prepare_owner_dividend_payment(command)
            if prepared.replay is not None:
                return prepared.replay
            ledger = self._ledger_facade_factory(transaction)
            posted = await ledger.post_owner_dividend_payment(
                PostOwnerDividendPaymentCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    payment_event_id=LedgerSourceRecordId(str(command.payment_event_id)),
                    payment_amount=_money_from_ore(prepared.payment_amount_ore),
                    dividend_payable_account=prepared.dividend_payable_account,
                    bank_account=prepared.bank_account,
                    accounting_policy_version=prepared.accounting_policy_version,
                    ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
                )
            )
            if posted.entry_id != LedgerEntryId(str(command.ledger_entry_id)):
                raise CorporateGovernanceError.unavailable()
            await transaction.claim_transaction_for_external_action(
                ClaimBankTransactionForExternalActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    transaction_id=BankTransactionId(str(command.bank_transaction_id)),
                    transaction_date=prepared.bank_transaction_date,
                    signed_amount=prepared.bank_signed_amount,
                    source_hash=prepared.bank_source_sha256,
                    action_reference=ExternalActionReference(str(command.holding_action_id)),
                ),
                accounting_entry_id=BankingAccountingEntryReference(
                    str(posted.entry_id)
                ),
            )
            return await transaction.complete_owner_dividend_payment(
                command,
                AccountingEntryReference(str(posted.entry_id)),
                prepared,
            )

    async def record_shareholder_loan(
        self,
        access_token: str,
        command: RecordShareholderLoanCommand,
    ) -> RecordedShareholderLoan:
        session = await self._session(access_token, command.actor_id)
        loan = self._service.validate_shareholder_loan(command)
        async with session.transaction() as transaction:
            await self._require_owner(transaction, command.company_id)
            prepared = await transaction.prepare_shareholder_loan(command, loan)
            if prepared.replay is not None:
                return prepared.replay
            if command.document_id is not None:
                documents = await self._documents_session_factory.session(access_token)
                if documents.actor_id != command.actor_id:
                    raise CorporateGovernanceError.forbidden()
                records = await documents.list_documents((command.company_id,))
                record = next(
                    (
                        item
                        for item in records
                        if str(item.document_id) == str(command.document_id)
                    ),
                    None,
                )
                if (
                    record is None
                    or record.company_id != command.company_id
                    or record.income_year != command.income_year
                    or record.status
                    in {DocumentStatus.QUARANTINED, DocumentStatus.REMOVED}
                ):
                    raise CorporateGovernanceError.precondition(
                        CorporateGovernanceErrorCode.INVALID_INPUT,
                        "Shareholder-loan document evidence does not match the company year.",
                    )
            ledger = self._ledger_facade_factory(transaction)
            directions = {
                "shareholder_to_company": LedgerShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
                "company_to_corporate_shareholder": (
                    LedgerShareholderLoanDirection.COMPANY_TO_CORPORATE_SHAREHOLDER
                ),
            }
            posted = await ledger.post_shareholder_loan(
                PostShareholderLoanCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    counterparty_name=prepared.loan.counterparty_name,
                    direction=directions[prepared.loan.direction.value],
                    amount=_money_from_ore(prepared.loan.amount_ore),
                    ledger_entry_id=LedgerEntryId(str(command.ledger_entry_id)),
                )
            )
            if posted.entry_id != LedgerEntryId(str(command.ledger_entry_id)):
                raise CorporateGovernanceError.unavailable()
            if command.bank_transaction_id is not None:
                if (
                    prepared.bank_transaction_date is None
                    or prepared.bank_signed_amount is None
                    or prepared.bank_source_sha256 is None
                ):
                    raise CorporateGovernanceError.unavailable()
                await transaction.claim_transaction_for_external_action(
                    ClaimBankTransactionForExternalActionCommand(
                        company_id=command.company_id,
                        actor_id=command.actor_id,
                        correlation_id=command.correlation_id,
                        idempotency_key=command.idempotency_key,
                        income_year=command.income_year,
                        transaction_id=BankTransactionId(
                            str(command.bank_transaction_id)
                        ),
                        transaction_date=prepared.bank_transaction_date,
                        signed_amount=prepared.bank_signed_amount,
                        source_hash=prepared.bank_source_sha256,
                        action_reference=ExternalActionReference(
                            str(command.action_id)
                        ),
                    ),
                    accounting_entry_id=BankingAccountingEntryReference(
                        str(posted.entry_id)
                    ),
                )
            return await transaction.complete_shareholder_loan(
                command,
                AccountingEntryReference(str(posted.entry_id)),
                prepared,
            )


__all__ = ["CorporateGovernanceApplication", "LedgerFacadeFactory"]
