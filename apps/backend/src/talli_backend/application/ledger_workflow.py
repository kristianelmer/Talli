"""Thin authenticated application wrapper around the ledger capability."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from talli_backend.application.ledger_session import (
    AuthenticatedLedgerSession,
    LedgerAuthenticationError,
    LedgerSessionFactory,
    LedgerWorkflowTransaction,
)
from talli_backend.application.new_year_opening import (
    OpeningSnapshotCursor,
    OpeningSnapshotPage,
)
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    CompanyYearCloseAssessment,
    LedgerCommand,
    LedgerCommands,
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerError,
    LedgerFactReference,
    LedgerPersistence,
    LedgerQueries,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LockPeriodCommand,
    OpeningBalanceCategory,
    OpeningBalanceComponent,
    OpeningBankLoanComponent,
    OpeningCapitalIncreaseComponent,
    OpeningCapitalReductionComponent,
    OpeningDividendPayableComponent,
    OpeningDividendReceivableComponent,
    OpeningInvestmentComponent,
    OpeningPositionComponent,
    OpeningPositionMode,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostedLedgerEntry,
    PostManualJournalCommand,
    PostTaxSettlementCommand,
    RebuildCompanyYearOpeningCommand,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEconomicFactCandidates,
    ReconstructionEconomicFactSnapshot,
    RecordReconstructionAssessmentCommand,
    RecordOpeningBankInputCommand,
    TaxSettlementKind,
)
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningShareholder,
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
    OpeningSnapshotCommands,
    ShareholderRegisterFilingError,
    create_opening_snapshot_service,
)
from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
)


@dataclass(frozen=True, slots=True)
class RecordAdministrativeCostCommand(LedgerCommand):
    bank_transaction_id: LedgerSourceRecordId
    category: AdministrativeCostCategory
    payee: str
    amount: Money
    paid_date: LocalDate
    document_id: LedgerSourceRecordId | None = None


@dataclass(frozen=True, slots=True)
class RecordTaxSettlementCommand(LedgerCommand):
    action_id: LedgerSourceRecordId
    settlement_date: LocalDate
    amount: Money
    settlement_kind: TaxSettlementKind
    document_status: str
    bank_transaction_id: LedgerSourceRecordId | None
    document_id: LedgerSourceRecordId | None


@dataclass(frozen=True, slots=True)
class LedgerWriterResult:
    posted_entry: PostedLedgerEntry | None
    result: dict[str, object]
    replayed: bool


def _replayed_writer(
    payload: dict[str, object],
    command: LedgerCommand,
    expected_kind: LedgerEntryKind | None,
) -> LedgerWriterResult:
    posted: PostedLedgerEntry | None = None
    if expected_kind is not None:
        try:
            posted = PostedLedgerEntry(
                entry_id=LedgerEntryId(str(payload["entryId"])),
                company_id=CompanyId(str(payload["companyId"])),
                income_year=IncomeYear(int(payload["incomeYear"])),
                entry_kind=LedgerEntryKind(str(payload["entryKind"])),
                posted_at=Timestamp(
                    datetime.fromisoformat(
                        str(payload["postedAt"]).replace("Z", "+00:00")
                    )
                ),
                replayed=True,
            )
        except (KeyError, TypeError, ValueError):
            raise LedgerError.unavailable() from None
        if (
            posted.company_id != command.company_id
            or posted.income_year != command.income_year
            or posted.entry_kind is not expected_kind
        ):
            raise LedgerError.unavailable()
    return LedgerWriterResult(posted_entry=posted, result=dict(payload), replayed=True)


@dataclass(frozen=True, slots=True)
class NewYearStartCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    bank_balance: Money
    share_capital: Money
    share_count: int
    nominal_value: Money
    shareholders: tuple[OpeningShareholder, ...]
    opening_mode: OpeningPositionMode = OpeningPositionMode.NEW_COMPANY
    opening_basis: LedgerFactReference | None = None
    opening_components: tuple[OpeningPositionComponent, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.bank_balance.currency != "NOK"
            or self.share_capital.currency != "NOK"
            or self.bank_balance.amount < 0
            or self.share_capital.amount < 0
        ):
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        if self.opening_mode is OpeningPositionMode.NEW_COMPANY:
            if self.opening_basis is not None or self.opening_components:
                raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        elif self.opening_basis is None or not self.opening_components:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        try:
            _opening_snapshot_command(self)
        except ShareholderRegisterFilingError:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")


@dataclass(frozen=True, slots=True)
class NewYearStartResult:
    setup_id: OpeningSnapshotId
    posted_entry: PostedLedgerEntry


def _opening_snapshot_command(
    command: NewYearStartCommand,
) -> RecordOpeningSnapshotCommand:
    return RecordOpeningSnapshotCommand(
        company_id=command.company_id,
        actor_id=command.actor_id,
        correlation_id=command.correlation_id,
        idempotency_key=command.idempotency_key,
        income_year=command.income_year,
        share_capital=command.share_capital,
        share_count=command.share_count,
        nominal_value=command.nominal_value,
        shareholders=command.shareholders,
    )


def _new_year_request(command: NewYearStartCommand) -> dict[str, object]:
    request: dict[str, object] = {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "bankBalance": format(command.bank_balance.amount, "f"),
        "shareCapital": format(command.share_capital.amount, "f"),
        "shareCount": command.share_count,
        "nominalValue": format(command.nominal_value.amount, "f"),
        "shareholders": [
            {
                "name": shareholder.name,
                "shareholderKind": shareholder.shareholder_kind,
                "nationalId": shareholder.national_id,
                "orgNumber": shareholder.org_number,
                "shareCount": shareholder.share_count,
            }
            for shareholder in command.shareholders
        ],
    }
    if command.opening_mode is OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION:
        opening_basis = command.opening_basis
        if opening_basis is None:  # narrowed by NewYearStartCommand
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        request.update({
            "openingMode": command.opening_mode.value,
            "openingBasis": _fact_reference_request(opening_basis),
            "openingComponents": [
                _opening_component_request(component)
                for component in command.opening_components
            ],
        })
    return request


def _fact_reference_request(source: LedgerFactReference) -> dict[str, object]:
    return {
        "capability": source.capability.value,
        "recordId": str(source.record_id),
        "revision": source.revision,
        "factSha256": source.fact_sha256,
    }


def _opening_component_request(component: OpeningPositionComponent) -> dict[str, object]:
    common: dict[str, object] = {
        "primarySource": _fact_reference_request(component.primary_source),
        "corroboratingSources": [
            _fact_reference_request(source)
            for source in component.corroborating_sources
        ],
    }
    if isinstance(component, OpeningBalanceComponent):
        return common | {
            "componentKind": "CLASSIFIED_BALANCE",
            "category": component.category.value,
            "referenceId": str(component.reference_id),
            "amount": format(component.amount.amount, "f"),
        }
    if isinstance(component, OpeningBankLoanComponent):
        return common | {
            "componentKind": "BANK_LOAN",
            "loanReferenceId": str(component.loan_reference_id),
            "maturity": component.maturity.value,
            "amount": format(component.amount.amount, "f"),
        }
    if isinstance(component, OpeningInvestmentComponent):
        return common | {
            "componentKind": "INVESTMENT",
            "investmentReferenceId": str(component.investment_reference_id),
            "classification": component.classification.value,
            "amount": format(component.amount.amount, "f"),
        }
    if isinstance(component, OpeningCapitalIncreaseComponent):
        return common | {
            "componentKind": "CAPITAL_INCREASE",
            "capitalIncreaseReferenceId": str(component.capital_increase_reference_id),
            "phase": component.phase.value,
            "nominalIncrease": format(component.nominal_increase.amount, "f"),
            "sharePremium": format(component.share_premium.amount, "f"),
        }
    if isinstance(component, OpeningCapitalReductionComponent):
        return common | {
            "componentKind": "CAPITAL_REDUCTION",
            "capitalReductionReferenceId": str(component.capital_reduction_reference_id),
            "recognition": component.recognition.value,
            "nominalReduction": format(component.nominal_reduction.amount, "f"),
        }
    if isinstance(component, OpeningDividendReceivableComponent):
        component_kind = "DIVIDEND_RECEIVABLE"
    elif isinstance(component, OpeningDividendPayableComponent):
        component_kind = "DIVIDEND_PAYABLE"
    else:
        raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
    return common | {
        "componentKind": component_kind,
        "decisionReferenceId": str(component.decision_reference_id),
        "amount": format(component.amount.amount, "f"),
    }


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _new_company_opening_command(
    command: NewYearStartCommand,
    setup_id: OpeningSnapshotId,
) -> RebuildCompanyYearOpeningCommand:
    request = _new_year_request(command)
    snapshot_record_id = LedgerSourceRecordId(f"opening-setup:{setup_id}")
    ledger_record_id = LedgerSourceRecordId(
        f"new-year-start:{command.idempotency_key}"
    )
    snapshot_source = LedgerFactReference(
        capability=LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
        record_id=snapshot_record_id,
        revision=1,
        fact_sha256=_canonical_sha256({"setupId": str(setup_id), **request}),
    )
    ledger_source = LedgerFactReference(
        capability=LedgerSourceCapability.LEDGER,
        record_id=ledger_record_id,
        revision=1,
        fact_sha256=_canonical_sha256({
            "operation": "new_year_start",
            "idempotencyKey": str(command.idempotency_key),
            "request": request,
        }),
    )
    components: list[OpeningPositionComponent] = []
    if command.bank_balance.amount > 0:
        components.append(OpeningBalanceComponent(
            category=OpeningBalanceCategory.BANK,
            reference_id=LedgerSourceRecordId(f"{snapshot_record_id}:bank"),
            amount=command.bank_balance,
            primary_source=ledger_source,
            corroborating_sources=(snapshot_source,),
        ))
    if command.share_capital.amount > 0:
        components.append(OpeningBalanceComponent(
            category=OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL,
            reference_id=LedgerSourceRecordId(f"{snapshot_record_id}:share-capital"),
            amount=command.share_capital,
            primary_source=snapshot_source,
            corroborating_sources=(ledger_source,),
        ))
    retained = command.bank_balance.amount - command.share_capital.amount
    if retained != 0:
        components.append(OpeningBalanceComponent(
            category=(
                OpeningBalanceCategory.RETAINED_EARNINGS
                if retained > 0
                else OpeningBalanceCategory.UNCOVERED_LOSS
            ),
            reference_id=LedgerSourceRecordId(f"{snapshot_record_id}:balancing-equity"),
            amount=Money.nok(abs(retained)),
            primary_source=ledger_source,
            corroborating_sources=(snapshot_source,),
        ))
    if not components:
        raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
    return RebuildCompanyYearOpeningCommand(
        company_id=command.company_id,
        actor_id=command.actor_id,
        correlation_id=command.correlation_id,
        idempotency_key=command.idempotency_key,
        income_year=command.income_year,
        opening_date=LocalDate(date(int(command.income_year), 1, 1)),
        mode=OpeningPositionMode.NEW_COMPANY,
        opening_basis=snapshot_source,
        components=tuple(components),
    )


def _new_year_result_payload(result: NewYearStartResult) -> dict[str, object]:
    posted = result.posted_entry
    return {
        "setupId": str(result.setup_id),
        "entryId": str(posted.entry_id),
        "companyId": str(posted.company_id),
        "incomeYear": int(posted.income_year),
        "entryKind": posted.entry_kind.value,
        "postedAt": posted.posted_at.value.isoformat(),
    }


def _replayed_new_year(
    payload: dict[str, object], command: NewYearStartCommand
) -> NewYearStartResult:
    try:
        setup_id = OpeningSnapshotId(str(UUID(str(payload["setupId"]))))
        posted = PostedLedgerEntry(
            entry_id=LedgerEntryId(str(payload["entryId"])),
            company_id=CompanyId(str(payload["companyId"])),
            income_year=IncomeYear(int(payload["incomeYear"])),
            entry_kind=LedgerEntryKind(str(payload["entryKind"])),
            posted_at=Timestamp(
                datetime.fromisoformat(str(payload["postedAt"]).replace("Z", "+00:00"))
            ),
            replayed=True,
        )
    except (KeyError, TypeError, ValueError):
        raise LedgerError.unavailable() from None
    if (
        posted.company_id != command.company_id
        or posted.income_year != command.income_year
        or posted.entry_kind is not LedgerEntryKind.OPENING_BALANCE
    ):
        raise LedgerError.unavailable()
    return NewYearStartResult(setup_id=setup_id, posted_entry=posted)


class LedgerFacade(LedgerCommands, LedgerQueries, Protocol):
    pass


LedgerFacadeFactory = Callable[[LedgerPersistence], LedgerFacade]
OpeningSnapshotFacadeFactory = Callable[
    [LedgerWorkflowTransaction], OpeningSnapshotCommands
]


class LedgerApplicationSession:
    def __init__(
        self,
        persistence: AuthenticatedLedgerSession,
        ledger: LedgerFacade,
        facade_factory: LedgerFacadeFactory,
        opening_snapshot_factory: OpeningSnapshotFacadeFactory,
    ) -> None:
        self._persistence = persistence
        self._ledger = ledger
        self._facade_factory = facade_factory
        self._opening_snapshot_factory = opening_snapshot_factory

    @property
    def actor_id(self) -> ActorId:
        return self._persistence.actor_id

    async def start_new_year(
        self, command: NewYearStartCommand
    ) -> NewYearStartResult:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()

        for attempt in range(2):
            try:
                return await self._start_new_year_once(command)
            except (LedgerError, ShareholderRegisterFilingError) as error:
                if (
                    error.category is not ErrorCategory.DEPENDENCY_UNAVAILABLE
                    or attempt == 1
                ):
                    raise
        raise LedgerError.unavailable()

    async def _start_new_year_once(
        self, command: NewYearStartCommand
    ) -> NewYearStartResult:
        operation_name = "new_year_start"
        request = _new_year_request(command)
        async with self._persistence.transaction() as transaction:
            replay = await transaction.claim_workflow(
                operation_name=operation_name,
                command=command,
                request=request,
            )
            if replay is not None:
                return _replayed_new_year(replay, command)

            setup_id = await self._opening_snapshot_factory(
                transaction,
            ).record_opening_snapshot(_opening_snapshot_command(command))
            ledger = self._facade_factory(transaction)
            await ledger.record_opening_bank_input(RecordOpeningBankInputCommand(
                company_id=command.company_id,
                actor_id=command.actor_id,
                correlation_id=command.correlation_id,
                idempotency_key=command.idempotency_key,
                income_year=command.income_year,
                snapshot_id=str(setup_id),
                bank_balance=command.bank_balance,
            ))
            if command.opening_mode is OpeningPositionMode.NEW_COMPANY:
                opening_command = _new_company_opening_command(command, setup_id)
            else:
                opening_basis = command.opening_basis
                if opening_basis is None:  # narrowed by NewYearStartCommand
                    raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
                opening_command = RebuildCompanyYearOpeningCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    opening_date=LocalDate(date(int(command.income_year), 1, 1)),
                    mode=command.opening_mode,
                    opening_basis=opening_basis,
                    components=command.opening_components,
                )
            posted_entry = await ledger.rebuild_company_year_opening(
                opening_command
            )
            result = NewYearStartResult(
                setup_id=setup_id,
                posted_entry=posted_entry,
            )
            await transaction.complete_workflow(
                operation_name=operation_name,
                command=command,
                request=request,
                result=_new_year_result_payload(result),
            )
            return result

    async def post_administrative_cost(
        self, command: PostAdministrativeCostCommand
    ) -> PostedLedgerEntry:
        return await self._ledger.post_administrative_cost(command)

    async def record_administrative_cost(
        self, command: RecordAdministrativeCostCommand
    ) -> LedgerWriterResult:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        async with self._persistence.transaction() as transaction:
            prepared = await transaction.prepare_administrative_cost(command)
            replay = prepared.get("replay")
            if replay is not None:
                if not isinstance(replay, dict):
                    raise LedgerError.unavailable()
                return _replayed_writer(
                    replay, command, LedgerEntryKind.ADMINISTRATIVE_COST
                )
            posted = await self._facade_factory(
                transaction
            ).post_administrative_cost(
                PostAdministrativeCostCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    bank_transaction_id=command.bank_transaction_id,
                    category=command.category,
                    payee=command.payee,
                    amount=command.amount,
                    paid_date=command.paid_date,
                    document_id=command.document_id,
                )
            )
            result = await transaction.complete_administrative_cost(
                command, posted, prepared
            )
            return LedgerWriterResult(
                posted_entry=posted,
                result=result,
                replayed=False,
            )

    async def record_tax_settlement(
        self, command: RecordTaxSettlementCommand
    ) -> LedgerWriterResult:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        async with self._persistence.transaction() as transaction:
            prepared = await transaction.prepare_tax_settlement(command)
            replay = prepared.get("replay")
            if replay is not None:
                if not isinstance(replay, dict):
                    raise LedgerError.unavailable()
                return _replayed_writer(replay, command, LedgerEntryKind.TAX_SETTLEMENT)
            posted = await self._facade_factory(transaction).post_tax_settlement(
                PostTaxSettlementCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    settlement_id=command.action_id,
                    settlement_kind=command.settlement_kind,
                    amount=command.amount,
                )
            )
            result = await transaction.complete_tax_settlement(
                command, posted, prepared
            )
            return LedgerWriterResult(posted, result, False)

    async def post_manual_journal(
        self, command: PostManualJournalCommand
    ) -> PostedLedgerEntry:
        return await self._ledger.post_manual_journal(command)

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        return await self._ledger.lock_period(command)

    async def record_reconstruction_assessment(
        self, command: RecordReconstructionAssessmentCommand
    ) -> ReconstructionAssessment:
        return await self._ledger.record_reconstruction_assessment(command)

    async def get_reconstruction_economic_fact_candidates(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        as_of: LocalDate,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactCandidates:
        return await self._ledger.get_reconstruction_economic_fact_candidates(
            actor_id=actor_id,
            company_id=company_id,
            income_year=income_year,
            as_of=as_of,
            correlation_id=correlation_id,
        )

    async def get_reconstruction_economic_facts(
        self,
        *,
        actor_id: ActorId,
        assessment_id: ReconstructionAssessmentId,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactSnapshot:
        return await self._ledger.get_reconstruction_economic_facts(
            actor_id=actor_id,
            assessment_id=assessment_id,
            correlation_id=correlation_id,
        )

    async def get_reconstruction_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> ReconstructionAssessment:
        return await self._ledger.get_reconstruction_assessment(
            actor_id=actor_id,
            company_id=company_id,
            income_year=income_year,
            correlation_id=correlation_id,
        )

    async def get_company_year_close_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> CompanyYearCloseAssessment:
        return await self._ledger.get_company_year_close_assessment(
            actor_id=actor_id,
            company_id=company_id,
            income_year=income_year,
            correlation_id=correlation_id,
        )

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage:
        return await self._ledger.list_entries(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage:
        return await self._ledger.list_period_locks(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_opening_snapshots(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: OpeningSnapshotCursor | None,
        limit: int,
    ) -> OpeningSnapshotPage:
        return await self._persistence.list_opening_snapshots(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )


class LedgerApplication:
    def __init__(
        self,
        sessions: LedgerSessionFactory,
        facade_factory: LedgerFacadeFactory,
        opening_snapshot_factory: OpeningSnapshotFacadeFactory = (
            create_opening_snapshot_service
        ),
    ) -> None:
        self._sessions = sessions
        self._facade_factory = facade_factory
        self._opening_snapshot_factory = opening_snapshot_factory

    async def session(self, access_token: str) -> LedgerApplicationSession:
        persistence = await self._sessions.session(access_token)
        return LedgerApplicationSession(
            persistence,
            self._facade_factory(persistence),
            self._facade_factory,
            self._opening_snapshot_factory,
        )


__all__ = [
    "LedgerApplication",
    "LedgerAuthenticationError",
    "LedgerFacadeFactory",
    "LedgerSessionFactory",
    "LedgerWriterResult",
    "NewYearStartCommand",
    "NewYearStartResult",
    "RecordAdministrativeCostCommand",
    "RecordTaxSettlementCommand",
]
