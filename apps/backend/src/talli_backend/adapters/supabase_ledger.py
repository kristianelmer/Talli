"""Verified-actor, restricted PostgreSQL adapter for the ledger capability."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import psycopg
from psycopg.rows import dict_row

from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.application.ledger_workflow import (
    FinalizeCorporateDecisionCommand,
    LedgerApplication,
    LedgerSessionFactory,
    NewYearStartCommand,
    RecordAdministrativeCostCommand,
    RecordInvestmentDividendCommand,
    RecordOwnerDividendPaymentCommand,
    RecordShareholderLoanCommand,
    RecordTaxSettlementCommand,
)
from talli_backend.application.opening_snapshot_compatibility import (
    LegacyOpeningShareholderView,
    LegacyOpeningSnapshotCursor,
    LegacyOpeningSnapshotPage,
    LegacyOpeningSnapshotView,
)
from talli_backend.modules.ledger.public import (
    ApprovedLossCoverageCapitalReductionFacts,
    BankLoanEvent,
    BankLoanReferenceId,
    CapitalIncreasePhase,
    CapitalIncreaseReferenceId,
    CapitalReductionRecognition,
    CapitalReductionReferenceId,
    CashCapitalIncreaseFacts,
    CloseCompanyYearCommand,
    CompanyYearCloseAssessment,
    CompanyYearCloseAssessmentId,
    CompanyYearCloseEvidence,
    CompanyYearCloseGapCode,
    CompanyYearCloseLockId,
    CompanyYearCloseState,
    CompiledOpeningPositionComponent,
    CorrectedLedgerEntries,
    CorrectHoldingActionCommand,
    DividendDecisionReferenceId,
    InvestmentDividendFacts,
    LedgerCommand,
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerEntryView,
    LedgerError,
    LedgerFactReference,
    LedgerFactRole,
    LedgerLine,
    LedgerPage,
    LedgerPersistence,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LockPeriodCommand,
    OrdinaryBankLoanFacts,
    PeriodLock,
    PeriodLockId,
    PeriodLockPage,
    PostedLedgerEntry,
    RebuildCompanyYearOpeningCommand,
    RecognizeHoldingActionCommand,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEconomicFactCandidates,
    ReconstructionEconomicFact,
    ReconstructionEconomicFactCorrection,
    ReconstructionEconomicFactSnapshot,
    ReconstructionEconomicFactSource,
    ReconstructionEvidence,
    ReconstructionGapCode,
    ReconstructionState,
    RecordReconstructionAssessmentCommand,
    ledger_persistence_adapter,
)
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
    UserId,
)


@dataclass(frozen=True)
class LedgerSupabaseConfiguration:
    url: str
    anon_key: str
    database_url: str = ""


@dataclass(frozen=True)
class _VerifiedActor:
    actor_id: ActorId
    claims_json: str


def _validated_origin(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
        hostname = parsed.hostname
    except (ValueError, UnicodeError):
        raise ValueError("Supabase origin is invalid") from None
    is_loopback = hostname == "localhost"
    if hostname is not None and not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and not is_loopback)
    ):
        raise ValueError("Supabase origin is unsafe")
    return f"{parsed.scheme}://{parsed.netloc}"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _timestamp(value: object) -> Timestamp:
    if isinstance(value, datetime):
        return Timestamp(value)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return Timestamp(parsed)
    raise ValueError("ledger timestamp is invalid")


def _actor(value: object) -> ActorId:
    return ActorId(kind=ActorKind.USER, subject=UserId(str(value)))


def _money(value: object, currency: object = "NOK") -> Money:
    if str(currency) != "NOK":
        raise ValueError("ledger currency is invalid")
    if isinstance(value, Decimal):
        return Money.nok(value)
    return Money.nok(str(value))


def _line_payload(line: LedgerLine) -> dict[str, str]:
    return {
        "account": line.account,
        "description": line.description,
        "debit": format(line.debit.amount, "f"),
        "credit": format(line.credit.amount, "f"),
        "currency": line.debit.currency.value,
    }


def _risk_payload(flag: LedgerRiskFlag) -> dict[str, str]:
    return {"code": flag.code.value, "account": flag.account}


def _fact_reference_payload(
    reference: LedgerFactReference,
    *,
    primary: bool,
) -> dict[str, object]:
    return {
        "role": "PRIMARY" if primary else "CORROBORATING",
        "capability": reference.capability.value,
        "recordId": str(reference.record_id),
        "revision": reference.revision,
        "factSha256": reference.fact_sha256,
    }


def _optional_source(value: LedgerSourceRecordId | None) -> str | None:
    return str(value) if value is not None else None


def _reconstruction_evidence_payload(
    evidence: ReconstructionEvidence,
) -> dict[str, object]:
    return {
        "kind": evidence.kind.value,
        "issuer": evidence.issuer.value,
        "confirmation": evidence.confirmation.value,
        "sourceRecordId": str(evidence.source_record_id),
        "sourceRevision": evidence.source_revision,
        "factSha256": evidence.fact_sha256,
        "coverageFrom": (
            evidence.coverage_from.value.isoformat()
            if evidence.coverage_from is not None
            else None
        ),
        "coverageThrough": (
            evidence.coverage_through.value.isoformat()
            if evidence.coverage_through is not None
            else None
        ),
        "gapCode": evidence.gap_code.value if evidence.gap_code is not None else None,
    }


def _reconstruction_assessment(row: Mapping[str, object]) -> ReconstructionAssessment:
    raw_gaps = row.get("gap_codes")
    if not isinstance(raw_gaps, list):
        raise ValueError("reconstruction gaps are invalid")
    ledger_state_digest = row.get("ledger_state_digest")
    return ReconstructionAssessment(
        assessment_id=ReconstructionAssessmentId(str(row["assessment_id"])),
        company_id=CompanyId(str(row["company_id"])),
        income_year=IncomeYear(int(row["income_year"])),
        as_of=LocalDate(
            row["as_of"]
            if isinstance(row["as_of"], date)
            else date.fromisoformat(str(row["as_of"]))
        ),
        state=ReconstructionState(str(row["state"])),
        gap_codes=tuple(ReconstructionGapCode(str(value)) for value in raw_gaps),
        evidence_digest=str(row["evidence_digest"]),
        ledger_state_digest=(
            str(ledger_state_digest) if ledger_state_digest is not None else None
        ),
        recorded_at=_timestamp(row["recorded_at"]),
        replayed=bool(row["replayed"]),
        economic_facts_digest=(
            str(row["economic_facts_digest"])
            if row.get("economic_facts_digest") is not None
            else None
        ),
        economic_fact_count=(
            int(row["economic_fact_count"])
            if row.get("economic_fact_count") is not None
            else None
        ),
        source_evidence_digest=(
            str(row["source_evidence_digest"])
            if row.get("source_evidence_digest") is not None
            else None
        ),
        source_evidence_count=(
            int(row["source_evidence_count"])
            if row.get("source_evidence_count") is not None
            else None
        ),
    )


def _company_year_close_evidence_payload(
    evidence: CompanyYearCloseEvidence,
) -> dict[str, object]:
    return {
        "kind": evidence.kind.value,
        "issuer": evidence.issuer.value,
        "status": evidence.confirmation.value,
        "sourceRecordId": str(evidence.source_record_id),
        "revision": evidence.revision,
        "factSha256": evidence.fact_sha256,
        "ledgerStateDigest": evidence.ledger_state_digest,
        "coverageThrough": evidence.coverage_through.value.isoformat(),
        "gapCode": evidence.gap_code.value if evidence.gap_code is not None else None,
        "outputs": [
            {
                "kind": output.kind.value,
                "sourceRecordId": str(output.source_record_id),
                "revision": output.revision,
                "factSha256": output.fact_sha256,
                "economicFactsDigest": output.economic_facts_digest,
            }
            for output in evidence.outputs
        ],
    }


def _company_year_close_assessment(
    row: Mapping[str, object],
) -> CompanyYearCloseAssessment:
    raw_gaps = row.get("gap_codes")
    if not isinstance(raw_gaps, list):
        raise ValueError("company-year close gaps are invalid")
    close_lock_id = row.get("close_lock_id")
    return CompanyYearCloseAssessment(
        assessment_id=CompanyYearCloseAssessmentId(str(row["assessment_id"])),
        close_lock_id=(
            CompanyYearCloseLockId(str(close_lock_id))
            if close_lock_id is not None
            else None
        ),
        reconstruction_assessment_id=ReconstructionAssessmentId(
            str(row["reconstruction_assessment_id"])
        ),
        company_id=CompanyId(str(row["company_id"])),
        income_year=IncomeYear(int(row["income_year"])),
        period_end=LocalDate(
            row["period_end"]
            if isinstance(row["period_end"], date)
            else date.fromisoformat(str(row["period_end"]))
        ),
        state=CompanyYearCloseState(str(row["state"])),
        gap_codes=tuple(CompanyYearCloseGapCode(str(value)) for value in raw_gaps),
        evidence_digest=str(row["evidence_digest"]),
        ledger_state_digest=str(row["ledger_state_digest"]),
        recorded_at=_timestamp(row["recorded_at"]),
        is_current=bool(row["is_current"]),
        replayed=bool(row["replayed"]),
    )


def _posted_entry(row: Mapping[str, object]) -> PostedLedgerEntry:
    return PostedLedgerEntry(
        entry_id=LedgerEntryId(str(row["ledger_entry_id"])),
        company_id=CompanyId(str(row["company_id"])),
        income_year=IncomeYear(int(row["income_year"])),
        entry_kind=LedgerEntryKind(str(row["entry_kind"])),
        posted_at=_timestamp(row["posted_at"]),
        replayed=bool(row["replayed"]),
    )


def _writer_metadata(command: LedgerCommand) -> dict[str, object]:
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "idempotencyKey": str(command.idempotency_key),
        "correlationId": str(command.correlation_id),
    }


def _writer_payload(command: LedgerCommand) -> dict[str, object]:
    payload = _writer_metadata(command)
    if isinstance(command, RecordAdministrativeCostCommand):
        payload.update(
            bankTransactionId=str(command.bank_transaction_id),
            category=command.category.value,
            payee=command.payee,
            amount=format(command.amount.amount, "f"),
            paidDate=command.paid_date.value.isoformat(),
            documentId=_optional_source(command.document_id),
        )
    elif isinstance(command, RecordInvestmentDividendCommand):
        payload.update(
            actionId=str(command.action_id),
            payingCompanyName=command.paying_company_name,
            declaredDate=command.declared_date.value.isoformat(),
            paidDate=command.paid_date.value.isoformat(),
            grossAmount=format(command.gross_amount.amount, "f"),
            linkedInvestmentId=_optional_source(command.linked_investment_id),
            taxTreatment=command.tax_treatment,
            bankTransactionId=_optional_source(command.bank_transaction_id),
            documentId=_optional_source(command.document_id),
            documentStatus=command.document_status,
        )
    elif isinstance(command, RecordShareholderLoanCommand):
        direction = {
            "SHAREHOLDER_TO_COMPANY": "shareholder_to_company",
            "COMPANY_TO_CORPORATE_SHAREHOLDER": "company_to_corporate_shareholder",
        }[command.direction.value]
        payload.update(
            actionId=str(command.action_id),
            loanDate=command.loan_date.value.isoformat(),
            amount=format(command.amount.amount, "f"),
            direction=direction,
            counterpartyName=command.counterparty_name,
            documentStatus=command.document_status,
            interestModelled=command.interest_modelled,
            relatedPartySecurity=command.related_party_security,
            bankTransactionId=_optional_source(command.bank_transaction_id),
            documentId=_optional_source(command.document_id),
        )
    elif isinstance(command, RecordTaxSettlementCommand):
        payload.update(
            actionId=str(command.action_id),
            settlementDate=command.settlement_date.value.isoformat(),
            amount=format(command.amount.amount, "f"),
            settlementKind=command.settlement_kind.value,
            documentStatus=command.document_status,
            bankTransactionId=_optional_source(command.bank_transaction_id),
            documentId=_optional_source(command.document_id),
        )
    elif isinstance(command, FinalizeCorporateDecisionCommand):
        payload.update(
            decisionId=str(command.decision_id),
            setId=str(command.set_id),
            decisionHash=command.decision_hash,
            finalizationId=str(command.finalization_id),
            holdingActionId=_optional_source(command.holding_action_id),
            ledgerEntryId=(
                str(command.ledger_entry_id)
                if command.ledger_entry_id is not None
                else None
            ),
        )
    elif isinstance(command, RecordOwnerDividendPaymentCommand):
        payload.update(
            decisionId=str(command.decision_id),
            setId=str(command.set_id),
            decisionHash=command.decision_hash,
            bankTransactionId=str(command.bank_transaction_id),
            holdingActionId=str(command.holding_action_id),
            ledgerEntryId=str(command.ledger_entry_id),
        )
    else:
        raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
    return payload


def _map_database_error(message: str) -> LedgerError:
    definitions = (
        ("ledger_not_found", LedgerError.not_found()),
        ("ledger_forbidden", LedgerError.forbidden()),
        (
            "ledger_period_locked",
            LedgerError.precondition_failed("LEDGER_PERIOD_LOCKED"),
        ),
        (
            "ledger_prior_year_correction_policy_unresolved",
            LedgerError.precondition_failed(
                "LEDGER_PRIOR_YEAR_CORRECTION_POLICY_UNRESOLVED"
            ),
        ),
        (
            "ledger_company_year_not_admitted",
            LedgerError.precondition_failed("LEDGER_COMPANY_YEAR_NOT_ADMITTED"),
        ),
        (
            "ledger_company_year_close_evidence_invalid",
            LedgerError.precondition_failed(
                "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
            ),
        ),
        (
            "ledger_company_year_close_reconstruction_stale",
            LedgerError.precondition_failed(
                "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
            ),
        ),
        (
            "ledger_reconstruction_stale",
            LedgerError.precondition_failed("LEDGER_RECONSTRUCTION_STALE"),
        ),
        (
            "ledger_reconstruction_economic_facts_invalid",
            LedgerError.invalid_input(
                "LEDGER_RECONSTRUCTION_ECONOMIC_FACTS_INVALID"
            ),
        ),
        (
            "ledger_reconstruction_source_evidence_invalid",
            LedgerError.invalid_input(
                "LEDGER_RECONSTRUCTION_SOURCE_EVIDENCE_INVALID"
            ),
        ),
        (
            "ledger_bank_loan_already_exists",
            LedgerError.conflict("LEDGER_BANK_LOAN_ALREADY_EXISTS"),
        ),
        (
            "ledger_bank_loan_event_invalid",
            LedgerError.precondition_failed("LEDGER_BANK_LOAN_EVENT_INVALID"),
        ),
        (
            "ledger_opening_loan_anchor_missing",
            LedgerError.precondition_failed("LEDGER_OPENING_LOAN_ANCHOR_MISSING"),
        ),
        (
            "ledger_bank_loan_principal_exceeded",
            LedgerError.precondition_failed("LEDGER_BANK_LOAN_PRINCIPAL_EXCEEDED"),
        ),
        (
            "ledger_cash_capital_increase_phase_invalid",
            LedgerError.precondition_failed(
                "LEDGER_CASH_CAPITAL_INCREASE_PHASE_INVALID"
            ),
        ),
        (
            "ledger_cash_capital_increase_phase_missing",
            LedgerError.precondition_failed(
                "LEDGER_CASH_CAPITAL_INCREASE_PHASE_MISSING"
            ),
        ),
        (
            "ledger_cash_capital_increase_amount_mismatch",
            LedgerError.precondition_failed(
                "LEDGER_CASH_CAPITAL_INCREASE_AMOUNT_MISMATCH"
            ),
        ),
        (
            "ledger_cash_capital_increase_phase_already_recorded",
            LedgerError.conflict(
                "LEDGER_CASH_CAPITAL_INCREASE_PHASE_ALREADY_RECORDED"
            ),
        ),
        (
            "ledger_opening_capital_increase_anchor_missing",
            LedgerError.precondition_failed(
                "LEDGER_OPENING_CAPITAL_INCREASE_ANCHOR_MISSING"
            ),
        ),
        (
            "ledger_loss_coverage_capital_reduction_phase_invalid",
            LedgerError.precondition_failed(
                "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_INVALID"
            ),
        ),
        (
            "ledger_loss_coverage_capital_reduction_amount_mismatch",
            LedgerError.precondition_failed(
                "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_AMOUNT_MISMATCH"
            ),
        ),
        (
            "ledger_loss_coverage_capital_reduction_phase_already_recorded",
            LedgerError.conflict(
                "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_ALREADY_RECORDED"
            ),
        ),
        (
            "ledger_opening_capital_reduction_anchor_missing",
            LedgerError.precondition_failed(
                "LEDGER_OPENING_CAPITAL_REDUCTION_ANCHOR_MISSING"
            ),
        ),
        (
            "ledger_received_dividend_already_settled",
            LedgerError.conflict("LEDGER_RECEIVED_DIVIDEND_ALREADY_SETTLED"),
        ),
        (
            "ledger_received_dividend_decision_invalid",
            LedgerError.precondition_failed(
                "LEDGER_RECEIVED_DIVIDEND_DECISION_INVALID"
            ),
        ),
        (
            "ledger_source_capability_mismatch",
            LedgerError.precondition_failed("LEDGER_SOURCE_CAPABILITY_MISMATCH"),
        ),
        (
            "ledger_opening_already_exists",
            LedgerError.conflict("LEDGER_OPENING_ALREADY_EXISTS"),
        ),
        (
            "ledger_opening_balance_invalid",
            LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID"),
        ),
        (
            "ledger_opening_evidence_invalid",
            LedgerError.precondition_failed("LEDGER_OPENING_EVIDENCE_INVALID"),
        ),
        (
            "ledger_opening_source_overlap",
            LedgerError.invalid_input("LEDGER_OPENING_SOURCE_OVERLAP"),
        ),
        (
            "ledger_entry_already_corrected",
            LedgerError.conflict("LEDGER_ENTRY_ALREADY_CORRECTED"),
        ),
        (
            "ledger_correction_original_kind_unsupported",
            LedgerError.precondition_failed(
                "LEDGER_CORRECTION_ORIGINAL_KIND_UNSUPPORTED"
            ),
        ),
        (
            "ledger_idempotency_key_reused",
            LedgerError.conflict("LEDGER_IDEMPOTENCY_KEY_REUSED"),
        ),
        (
            "ledger_idempotency_in_progress",
            LedgerError.conflict("LEDGER_IDEMPOTENCY_IN_PROGRESS"),
        ),
        (
            "ledger_invalid_cursor",
            LedgerError.invalid_input("LEDGER_INVALID_CURSOR"),
        ),
        ("ledger_invalid_input", LedgerError.invalid_input("LEDGER_INVALID_INPUT")),
    )
    for marker, mapped in definitions:
        if marker in message:
            return mapped
    return LedgerError.unavailable()


class SupabaseLedgerAdapter:
    """Authenticate one bearer and return a request-bound RLS persistence session."""

    def __init__(self, configuration: LedgerSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._origin = _validated_origin(configuration.url)
        self._anon_key = configuration.anon_key
        self._opener = build_opener(_RejectRedirects)

    @classmethod
    def from_environment(cls) -> SupabaseLedgerAdapter:
        return cls(
            LedgerSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            )
        )

    def _unavailable(self) -> LedgerError:
        return LedgerError.unavailable()

    async def _auth_user(self, access_token: str) -> Mapping[str, object]:
        if not self._origin or not self._anon_key or not access_token:
            raise self._unavailable()

        def send() -> Mapping[str, object]:
            request = Request(
                f"{self._origin}/auth/v1/user",
                method="GET",
                headers={
                    "apikey": self._anon_key,
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            try:
                with self._opener.open(request, timeout=5) as response:
                    if response.status != 200:
                        raise LedgerAuthenticationError
                    body = response.read(65_537)
                    if len(body) > 65_536:
                        raise self._unavailable()
                    decoded = json.loads(body.decode("utf-8"))
            except HTTPError as error:
                if error.code in {401, 403}:
                    raise LedgerAuthenticationError from None
                raise self._unavailable() from None
            except (URLError, TimeoutError, json.JSONDecodeError):
                raise self._unavailable() from None
            if not isinstance(decoded, Mapping):
                raise LedgerAuthenticationError
            return decoded

        return await asyncio.to_thread(send)

    async def _verified_actor(self, access_token: str) -> _VerifiedActor:
        identity = await self._auth_user(access_token)
        identity_id = identity.get("id")
        identity_email = identity.get("email")
        if not isinstance(identity_id, str) or not isinstance(identity_email, str):
            raise LedgerAuthenticationError
        try:
            payload = access_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
        except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise LedgerAuthenticationError from None
        if not isinstance(decoded, Mapping) or decoded.get("sub") != identity_id:
            raise LedgerAuthenticationError
        claims: dict[str, object] = {
            "sub": identity_id,
            "email": identity_email.strip().lower(),
            "role": "authenticated",
            "aal": decoded.get("aal") if decoded.get("aal") in {"aal1", "aal2"} else "aal1",
        }
        if isinstance(decoded.get("amr"), list):
            claims["amr"] = decoded["amr"]
        return _VerifiedActor(
            actor_id=_actor(identity_id),
            claims_json=json.dumps(claims, separators=(",", ":")),
        )

    async def session(self, access_token: str) -> SupabaseLedgerSession:
        verified = await self._verified_actor(access_token)
        return SupabaseLedgerSession(self._configuration.database_url, verified)


@ledger_persistence_adapter(LedgerPersistence)
class SupabaseLedgerSession:
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self) -> ActorId:
        return self._verified.actor_id

    def _unavailable(self) -> LedgerError:
        return LedgerError.unavailable()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SupabaseLedgerWorkflowTransaction]:
        if not self._database_url:
            raise self._unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection, connection.transaction():
                await connection.execute("set local role ledger_workflow_executor")
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                    (str(self.actor_id.subject),),
                )
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                    (self._verified.claims_json,),
                )
                yield SupabaseLedgerWorkflowTransaction(
                    self._database_url,
                    self._verified,
                    connection,
                )
        except LedgerError:
            raise
        except psycopg.OperationalError:
            raise self._unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_database_error(str(error)) from None

    async def _database_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        if not self._database_url:
            raise self._unavailable()

        def execute() -> list[Mapping[str, object]]:
            try:
                with psycopg.connect(
                    self._database_url,
                    connect_timeout=5,
                    row_factory=dict_row,
                ) as connection, connection.transaction():
                    connection.execute("set local role ledger_executor")
                    connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                        (str(self.actor_id.subject),),
                    )
                    connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                        (self._verified.claims_json,),
                    )
                    return list(connection.execute(query, parameters).fetchall())
            except psycopg.OperationalError:
                raise self._unavailable() from None
            except psycopg.DatabaseError as error:
                raise _map_database_error(str(error)) from None

        return await asyncio.to_thread(execute)

    async def _one_idempotent_row(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object]:
        for attempt in range(2):
            try:
                rows = await self._database_rows(query, parameters)
            except LedgerError as error:
                if error.code != "LEDGER_DEPENDENCY_UNAVAILABLE" or attempt == 1:
                    raise
                continue
            if len(rows) == 1:
                return rows[0]
            if attempt == 1:
                break
        raise self._unavailable()

    async def get_company_year_close_replay(
        self,
        command: CloseCompanyYearCommand,
        *,
        evidence: tuple[CompanyYearCloseEvidence, ...],
    ) -> CompanyYearCloseAssessment | None:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        rows = await self._database_rows(
            """
            select * from ledger.get_company_year_close_replay_v1(
              %s::text, %s::uuid, %s::integer, %s::date, %s::text,
              %s::uuid, %s::text, %s::jsonb, %s::text, %s::text
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                command.period_end.value,
                command.reason,
                str(command.reconstruction_assessment_id),
                command.reconstruction_evidence_digest,
                json.dumps(
                    [_company_year_close_evidence_payload(item) for item in evidence],
                    separators=(",", ":"),
                ),
                str(command.correlation_id),
                str(command.actor_id.subject),
            ),
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise self._unavailable()
        try:
            return _company_year_close_assessment(rows[0])
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def record_company_year_close(
        self,
        command: CloseCompanyYearCommand,
        *,
        evidence: tuple[CompanyYearCloseEvidence, ...],
        state: CompanyYearCloseState,
        gap_codes: tuple[CompanyYearCloseGapCode, ...],
    ) -> CompanyYearCloseAssessment:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        row = await self._one_idempotent_row(
            """
            select * from ledger.close_company_year_v1(
              %s::text, %s::uuid, %s::integer, %s::date, %s::text,
              %s::uuid, %s::text, %s::jsonb, %s::text, %s::text[],
              %s::text, %s::text
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                command.period_end.value,
                command.reason,
                str(command.reconstruction_assessment_id),
                command.reconstruction_evidence_digest,
                json.dumps(
                    [_company_year_close_evidence_payload(item) for item in evidence],
                    separators=(",", ":"),
                ),
                state.value,
                [code.value for code in gap_codes],
                str(command.correlation_id),
                str(command.actor_id.subject),
            ),
        )
        try:
            return _company_year_close_assessment(row)
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def _record_received_dividend(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        decision_entry_id: LedgerEntryId | None,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        facts = command.facts
        if not isinstance(facts, InvestmentDividendFacts):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        function_name = (
            "record_received_dividend_decision_v1"
            if decision_entry_id is None
            else "record_received_dividend_payment_v1"
        )
        decision_argument = (
            () if decision_entry_id is None else (str(decision_entry_id),)
        )
        decision_placeholder = "" if decision_entry_id is None else "%s::uuid, "
        row = await self._one_idempotent_row(
            f"""
            select * from ledger.{function_name}(
              %s::text, %s::uuid, %s::integer, {decision_placeholder}%s::text, %s::jsonb,
              %s::text, %s::text, %s::text, %s::text, %s::date,
              %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                *decision_argument,
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines], separators=(",", ":")
                ),
                command.primary_source.capability.value,
                str(command.primary_source.record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        return _posted_entry(row)

    async def _record_bank_loan(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        expected_event: BankLoanEvent,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        interest: Money,
        fee: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        facts = command.facts
        if (
            not isinstance(facts, OrdinaryBankLoanFacts)
            or facts.event is not expected_event
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if (
            loan_reference_id != facts.loan_reference_id
            or principal != facts.principal
            or interest != facts.interest
            or fee != facts.fee
            or sum((line.debit.amount for line in lines), Decimal("0.00"))
            != principal.amount + interest.amount + fee.amount
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        if expected_event is BankLoanEvent.DISBURSEMENT:
            function_name = "record_bank_loan_disbursement_v1"
            allocation_placeholders = "%s::numeric"
            allocations = (principal.amount,)
        else:
            function_name = "record_bank_loan_payment_v1"
            allocation_placeholders = "%s::numeric, %s::numeric, %s::numeric"
            allocations = (principal.amount, interest.amount, fee.amount)
        row = await self._one_idempotent_row(
            f"""
            select * from ledger.{function_name}(
              %s::text, %s::uuid, %s::integer, %s::text,
              {allocation_placeholders}, %s::text, %s::jsonb, %s::text,
              %s::text, %s::text, %s::text, %s::date, %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                str(loan_reference_id),
                *allocations,
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines], separators=(",", ":")
                ),
                command.primary_source.capability.value,
                str(command.primary_source.record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        return _posted_entry(row)

    async def record_bank_loan_disbursement(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_bank_loan(
            command,
            expected_event=BankLoanEvent.DISBURSEMENT,
            loan_reference_id=loan_reference_id,
            principal=principal,
            interest=Money.nok("0.00"),
            fee=Money.nok("0.00"),
            memo=memo,
            lines=lines,
        )

    async def record_bank_loan_payment(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        interest: Money,
        fee: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_bank_loan(
            command,
            expected_event=BankLoanEvent.PAYMENT,
            loan_reference_id=loan_reference_id,
            principal=principal,
            interest=interest,
            fee=fee,
            memo=memo,
            lines=lines,
        )

    async def _record_cash_capital_increase(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        expected_phase: CapitalIncreasePhase,
        function_name: str,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        facts = command.facts
        total = nominal_increase.amount + share_premium.amount
        expected_debit = (
            total * 2 if expected_phase is CapitalIncreasePhase.REGISTERED else total
        )
        if (
            not isinstance(facts, CashCapitalIncreaseFacts)
            or facts.phase is not expected_phase
            or capital_increase_reference_id
            != facts.capital_increase_reference_id
            or nominal_increase != facts.nominal_increase
            or share_premium != facts.share_premium
            or sum((line.debit.amount for line in lines), Decimal("0.00"))
            != expected_debit
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        row = await self._one_idempotent_row(
            f"""
            select * from ledger.{function_name}(
              %s::text, %s::uuid, %s::integer, %s::text, %s::numeric,
              %s::numeric, %s::text, %s::jsonb, %s::text, %s::text,
              %s::text, %s::text, %s::date, %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                str(capital_increase_reference_id),
                nominal_increase.amount,
                share_premium.amount,
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines], separators=(",", ":")
                ),
                command.primary_source.capability.value,
                str(command.primary_source.record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        return _posted_entry(row)

    async def record_cash_capital_increase_subscription(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_cash_capital_increase(
            command,
            expected_phase=CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            function_name="record_cash_capital_increase_subscription_v1",
            capital_increase_reference_id=capital_increase_reference_id,
            nominal_increase=nominal_increase,
            share_premium=share_premium,
            memo=memo,
            lines=lines,
        )

    async def record_cash_capital_increase_restricted_payment(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_cash_capital_increase(
            command,
            expected_phase=CapitalIncreasePhase.RESTRICTED_PAYMENT,
            function_name="record_cash_capital_increase_restricted_payment_v1",
            capital_increase_reference_id=capital_increase_reference_id,
            nominal_increase=nominal_increase,
            share_premium=share_premium,
            memo=memo,
            lines=lines,
        )

    async def record_cash_capital_increase_registration(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_cash_capital_increase(
            command,
            expected_phase=CapitalIncreasePhase.REGISTERED,
            function_name="record_cash_capital_increase_registration_v1",
            capital_increase_reference_id=capital_increase_reference_id,
            nominal_increase=nominal_increase,
            share_premium=share_premium,
            memo=memo,
            lines=lines,
        )

    async def _record_loss_coverage_capital_reduction(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        expected_recognition: CapitalReductionRecognition,
        function_name: str,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        facts = command.facts
        if (
            not isinstance(facts, ApprovedLossCoverageCapitalReductionFacts)
            or facts.recognition is not expected_recognition
            or capital_reduction_reference_id
            != facts.capital_reduction_reference_id
            or nominal_reduction != facts.nominal_reduction
            or sum((line.debit.amount for line in lines), Decimal("0.00"))
            != nominal_reduction.amount
            or sum((line.credit.amount for line in lines), Decimal("0.00"))
            != nominal_reduction.amount
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        row = await self._one_idempotent_row(
            f"""
            select * from ledger.{function_name}(
              %s::text, %s::uuid, %s::integer, %s::text, %s::numeric,
              %s::text, %s::jsonb, %s::text, %s::text, %s::text,
              %s::text, %s::date, %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                str(capital_reduction_reference_id),
                nominal_reduction.amount,
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines], separators=(",", ":")
                ),
                command.primary_source.capability.value,
                str(command.primary_source.record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        return _posted_entry(row)

    async def record_loss_coverage_capital_reduction_decision(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_loss_coverage_capital_reduction(
            command,
            expected_recognition=CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
            function_name="record_loss_coverage_capital_reduction_decision_v1",
            capital_reduction_reference_id=capital_reduction_reference_id,
            nominal_reduction=nominal_reduction,
            memo=memo,
            lines=lines,
        )

    async def record_loss_coverage_capital_reduction_registration(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_loss_coverage_capital_reduction(
            command,
            expected_recognition=CapitalReductionRecognition.REGISTERED,
            function_name="record_loss_coverage_capital_reduction_registration_v1",
            capital_reduction_reference_id=capital_reduction_reference_id,
            nominal_reduction=nominal_reduction,
            memo=memo,
            lines=lines,
        )

    async def record_loss_coverage_capital_reduction_direct_registration(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_loss_coverage_capital_reduction(
            command,
            expected_recognition=(
                CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION
            ),
            function_name=(
                "record_loss_coverage_capital_reduction_direct_registration_v1"
            ),
            capital_reduction_reference_id=capital_reduction_reference_id,
            nominal_reduction=nominal_reduction,
            memo=memo,
            lines=lines,
        )

    async def record_received_dividend_decision(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        return await self._record_received_dividend(
            command,
            decision_entry_id=None,
            memo=memo,
            lines=lines,
        )

    async def record_received_dividend_payment(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        decision_reference: LedgerEntryId | DividendDecisionReferenceId,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry:
        if isinstance(decision_reference, LedgerEntryId):
            return await self._record_received_dividend(
                command,
                decision_entry_id=decision_reference,
                memo=memo,
                lines=lines,
            )
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        facts = command.facts
        if not isinstance(facts, InvestmentDividendFacts):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        row = await self._one_idempotent_row(
            """
            select * from ledger.record_received_dividend_payment_by_reference_v1(
              %s::text, %s::uuid, %s::integer, %s::text, %s::text, %s::jsonb,
              %s::text, %s::text, %s::text, %s::text, %s::date,
              %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                str(decision_reference),
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines], separators=(",", ":")
                ),
                command.primary_source.capability.value,
                str(command.primary_source.record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        try:
            return _posted_entry(row)
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def correct_entry(
        self,
        command: CorrectHoldingActionCommand,
        *,
        entry_kind: LedgerEntryKind,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> CorrectedLedgerEntries:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        sources = (
            _fact_reference_payload(command.primary_source, primary=True),
            *(
                _fact_reference_payload(source, primary=False)
                for source in command.corroborating_sources
            ),
        )
        row = await self._one_idempotent_row(
            """
            select * from ledger.correct_entry_v1(
              %s::text, %s::uuid, %s::integer, %s::uuid, %s::text,
              %s::text, %s::text, %s::jsonb, %s::text, %s::text,
              %s::date, %s::text, %s::text, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                str(command.original_entry_id),
                command.reason,
                entry_kind.value,
                memo,
                json.dumps(
                    [_line_payload(line) for line in lines], separators=(",", ":")
                ),
                str(command.correlation_id),
                str(command.actor_id.subject),
                command.event_date.value,
                command.replacement.correction_scope.value,
                "ledger-supported-patterns-2026.1",
                json.dumps(sources, separators=(",", ":")),
            ),
        )
        return CorrectedLedgerEntries(
            reversal_entry_id=LedgerEntryId(str(row["reversal_entry_id"])),
            replacement_entry_id=LedgerEntryId(str(row["replacement_entry_id"])),
            company_id=CompanyId(str(row["company_id"])),
            income_year=IncomeYear(int(row["income_year"])),
            corrected_at=_timestamp(row["corrected_at"]),
            replayed=bool(row["replayed"]),
        )

    async def post_entry(
        self,
        command: LedgerCommand,
        *,
        entry_kind: LedgerEntryKind,
        memo: str,
        lines: tuple[LedgerLine, ...],
        risk_flags: tuple[LedgerRiskFlag, ...],
        warning_accepted: bool,
        source_capability: LedgerSourceCapability,
        source_record_id: LedgerSourceRecordId,
        requested_entry_id: LedgerEntryId | None = None,
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        lines_payload = [_line_payload(line) for line in lines]
        risks_payload = [_risk_payload(flag) for flag in risk_flags]
        parameters = (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                entry_kind.value,
                memo,
                json.dumps(lines_payload, separators=(",", ":")),
                json.dumps(risks_payload, separators=(",", ":")),
                warning_accepted,
                source_capability.value,
                str(source_record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
        )
        if isinstance(command, RecognizeHoldingActionCommand):
            if requested_entry_id is not None:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            sources = (
                _fact_reference_payload(command.primary_source, primary=True),
                *(
                    _fact_reference_payload(source, primary=False)
                    for source in command.corroborating_sources
                ),
            )
            row = await self._one_idempotent_row(
                """
                select * from ledger.post_supported_entry_v1(
                  %s::text, %s::uuid, %s::integer, %s::text, %s::text,
                  %s::jsonb, %s::text, %s::text, %s::text, %s::text,
                  %s::date, %s::text, %s::jsonb
                )
                """,
                (
                    str(command.idempotency_key),
                    str(command.company_id),
                    int(command.income_year),
                    entry_kind.value,
                    memo,
                    json.dumps(lines_payload, separators=(",", ":")),
                    source_capability.value,
                    str(source_record_id),
                    str(command.correlation_id),
                    str(command.actor_id.subject),
                    command.event_date.value,
                    "ledger-supported-patterns-2026.1",
                    json.dumps(sources, separators=(",", ":")),
                ),
            )
        elif requested_entry_id is None:
            row = await self._one_idempotent_row(
                """
                select * from ledger.post_entry(
                  %s::text, %s::uuid, %s::integer, %s::text, %s::text,
                  %s::jsonb, %s::jsonb, %s::boolean, %s::text, %s::text, %s::text, %s::text
                )
                """,
                parameters,
            )
        else:
            row = await self._one_idempotent_row(
                """
                select * from ledger.post_entry_with_id_v1(
                  %s::text, %s::uuid, %s::integer, %s::text, %s::text,
                  %s::jsonb, %s::jsonb, %s::boolean, %s::text, %s::text,
                  %s::text, %s::text, %s::uuid
                )
                """,
                (*parameters, str(requested_entry_id)),
            )
        return _posted_entry(row)

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        row = await self._one_idempotent_row(
            """
            select * from ledger.lock_period(
              %s::text, %s::uuid, %s::integer, %s::text, %s::text, %s::text
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                command.reason.strip(),
                str(command.correlation_id),
                str(command.actor_id.subject),
            ),
        )
        return PeriodLock(
            period_lock_id=PeriodLockId(str(row["period_lock_id"])),
            company_id=CompanyId(str(row["company_id"])),
            income_year=IncomeYear(int(row["income_year"])),
            reason=str(row["reason"]),
            locked_by=_actor(row["locked_by"]),
            locked_at=_timestamp(row["locked_at"]),
            replayed=bool(row["replayed"]),
        )

    async def record_reconstruction_assessment(
        self,
        command: RecordReconstructionAssessmentCommand,
        *,
        evidence: tuple[ReconstructionEvidence, ...],
        state: ReconstructionState,
        gap_codes: tuple[ReconstructionGapCode, ...],
    ) -> ReconstructionAssessment:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        row = await self._one_idempotent_row(
            """
            select * from ledger.record_reconstruction_assessment(
              %s::text, %s::uuid, %s::integer, %s::date, %s::jsonb, %s::uuid[],
              %s::text, %s::text[], %s::text, %s::text
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                command.as_of.value,
                json.dumps(
                    [_reconstruction_evidence_payload(item) for item in evidence],
                    separators=(",", ":"),
                ),
                [entry_id.value for entry_id in command.economic_fact_entry_ids],
                state.value,
                [code.value for code in gap_codes],
                str(command.correlation_id),
                str(command.actor_id.subject),
            ),
        )
        try:
            assessment = _reconstruction_assessment(row)
            return replace(
                assessment,
                source_evidence_digest=assessment.evidence_digest,
                source_evidence_count=len(evidence),
            )
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def rebuild_company_year_opening(
        self,
        command: RebuildCompanyYearOpeningCommand,
        *,
        components: tuple[CompiledOpeningPositionComponent, ...],
        lines: tuple[LedgerLine, ...],
        entry_sources: tuple[LedgerFactReference, ...],
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        expected_sources_list = [command.opening_basis]
        seen_sources = {
            (
                command.opening_basis.capability,
                command.opening_basis.record_id,
                command.opening_basis.revision,
            )
        }
        for component in components:
            for source in (
                component.primary_source,
                *component.corroborating_sources,
            ):
                identity = (source.capability, source.record_id, source.revision)
                if identity not in seen_sources:
                    seen_sources.add(identity)
                    expected_sources_list.append(source)
        expected_sources = tuple(expected_sources_list)
        if entry_sources != expected_sources:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        source_payload = tuple(
            _fact_reference_payload(source, primary=index == 0)
            for index, source in enumerate(entry_sources)
        )
        component_payload = tuple(
            {
                "ordinal": index,
                "componentKind": component.component_kind,
                "category": component.category.value,
                "referenceId": component.reference_id,
                "lifecyclePhase": component.lifecycle_phase,
                "amountNok": format(component.amount.amount, "f"),
                "nominalIncreaseNok": (
                    format(component.nominal_increase.amount, "f")
                    if component.nominal_increase is not None
                    else None
                ),
                "sharePremiumNok": (
                    format(component.share_premium.amount, "f")
                    if component.share_premium is not None
                    else None
                ),
                "nominalReductionNok": (
                    format(component.nominal_reduction.amount, "f")
                    if component.nominal_reduction is not None
                    else None
                ),
                "account": component.account,
                "balanceSide": "DEBIT" if component.is_debit else "CREDIT",
                "sources": [
                    _fact_reference_payload(component.primary_source, primary=True),
                    *(
                        _fact_reference_payload(source, primary=False)
                        for source in component.corroborating_sources
                    ),
                ],
            }
            for index, component in enumerate(components, start=1)
        )
        row = await self._one_idempotent_row(
            """
            select * from ledger.rebuild_company_year_opening_v1(
              %s::text, %s::uuid, %s::integer, %s::date, %s::text, %s::text,
              %s::jsonb, %s::text, %s::text, %s::text, %s::text,
              %s::jsonb, %s::jsonb
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                command.opening_date.value,
                command.mode.value,
                "Complete evidenced opening position",
                json.dumps([_line_payload(line) for line in lines], separators=(",", ":")),
                command.opening_basis.capability.value,
                str(command.opening_basis.record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
                json.dumps(source_payload, separators=(",", ":")),
                json.dumps(component_payload, separators=(",", ":")),
            ),
        )
        try:
            return _posted_entry(row)
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def get_reconstruction_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> ReconstructionAssessment:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.get_reconstruction_assessment_with_source_evidence_v1(%s::uuid, %s::integer, %s::text)",
            (str(company_id), int(income_year), str(actor_id.subject)),
        )
        if len(rows) != 1:
            raise LedgerError.not_found()
        try:
            return _reconstruction_assessment(rows[0])
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def get_reconstruction_economic_fact_candidates(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        as_of: LocalDate,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactCandidates:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.get_company_year_economic_fact_candidates_v1(%s::uuid, %s::integer, %s::date, %s::text)",
            (
                str(company_id),
                int(income_year),
                as_of.value,
                str(actor_id.subject),
            ),
        )
        if len(rows) != 1:
            raise LedgerError.not_found()
        row = rows[0]
        try:
            raw_ids = row["entry_ids"]
            if not isinstance(raw_ids, list):
                raise ValueError
            entry_ids = tuple(LedgerEntryId(str(value)) for value in raw_ids)
            if int(row["fact_count"]) != len(entry_ids):
                raise ValueError
            return ReconstructionEconomicFactCandidates(
                company_id=company_id,
                income_year=income_year,
                as_of=as_of,
                entry_ids=entry_ids,
                facts_digest=str(row["facts_digest"]),
            )
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def get_reconstruction_economic_facts(
        self,
        *,
        actor_id: ActorId,
        assessment_id: ReconstructionAssessmentId,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactSnapshot:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.get_reconstruction_economic_facts_v1(%s::uuid, %s::text)",
            (str(assessment_id), str(actor_id.subject)),
        )
        if len(rows) != 1:
            raise LedgerError.not_found()
        row = rows[0]
        try:
            raw_facts = row["facts"]
            if not isinstance(raw_facts, list):
                raise ValueError
            facts = tuple(self._reconstruction_economic_fact(fact) for fact in raw_facts)
            if int(row["fact_count"]) != len(facts):
                raise ValueError
            return ReconstructionEconomicFactSnapshot(
                assessment_id=ReconstructionAssessmentId(str(row["assessment_id"])),
                company_id=CompanyId(str(row["company_id"])),
                income_year=IncomeYear(int(row["income_year"])),
                as_of=LocalDate(
                    row["as_of"]
                    if isinstance(row["as_of"], date)
                    else date.fromisoformat(str(row["as_of"]))
                ),
                facts_digest=str(row["facts_digest"]),
                facts=facts,
            )
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def get_company_year_close_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> CompanyYearCloseAssessment:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.get_company_year_close_assessment_v1(%s::uuid, %s::integer, %s::text)",
            (str(company_id), int(income_year), str(actor_id.subject)),
        )
        if not rows:
            raise LedgerError.not_found()
        if len(rows) != 1:
            raise self._unavailable()
        try:
            return _company_year_close_assessment(rows[0])
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.list_entries(%s::uuid[], %s::text, %s::integer, %s::text)",
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor is not None else None,
                limit,
                str(actor_id.subject),
            ),
        )
        if len(rows) != 1:
            raise self._unavailable()
        items_payload = rows[0].get("items")
        if not isinstance(items_payload, list):
            raise self._unavailable()
        try:
            entries = tuple(self._entry_view(item) for item in items_payload)
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None
        return LedgerEntryPage(
            items=entries,
            page=LedgerPage(
                next_cursor=(
                    LedgerCursor(str(rows[0]["next_cursor"]))
                    if rows[0].get("next_cursor") is not None
                    else None
                ),
                has_more=bool(rows[0].get("has_more")),
            ),
        )

    async def list_opening_snapshots(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LegacyOpeningSnapshotCursor | None,
        limit: int,
    ) -> LegacyOpeningSnapshotPage:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from backend_system.list_opening_snapshots_legacy_v1(%s::uuid[], %s::text, %s::integer, %s::text)",
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor is not None else None,
                limit,
                str(actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
            raise self._unavailable()
        try:
            items = tuple(
                LegacyOpeningSnapshotView(
                    setup_id=str(item["setupId"]),
                    company_id=CompanyId(str(item["companyId"])),
                    income_year=IncomeYear(int(item["incomeYear"])),
                    bank_balance=_money(item["bankBalance"]),
                    share_capital=_money(item["shareCapital"]),
                    share_count=int(item["shareCount"]),
                    nominal_value=_money(item["nominalValue"]),
                    locked_at=_timestamp(item["lockedAt"]),
                    created_at=_timestamp(item["createdAt"]),
                    created_by=_actor(item["createdBy"]),
                    shareholders=tuple(
                        LegacyOpeningShareholderView(
                            shareholder_id=str(shareholder["shareholderId"]),
                            setup_id=str(shareholder["setupId"]),
                            company_id=CompanyId(str(shareholder["companyId"])),
                            name=str(shareholder["name"]),
                            shareholder_kind=shareholder["shareholderKind"],
                            national_id=(
                                str(shareholder["nationalId"])
                                if shareholder.get("nationalId") is not None
                                else None
                            ),
                            org_number=(
                                str(shareholder["orgNumber"])
                                if shareholder.get("orgNumber") is not None
                                else None
                            ),
                            share_count=int(shareholder["shareCount"]),
                        )
                        for shareholder in item["shareholders"]
                    ),
                )
                for item in rows[0]["items"]
            )
            return LegacyOpeningSnapshotPage(
                items=items,
                next_cursor=(
                    LegacyOpeningSnapshotCursor(str(rows[0]["next_cursor"]))
                    if rows[0].get("next_cursor") is not None
                    else None
                ),
                has_more=bool(rows[0].get("has_more")),
            )
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.list_period_locks(%s::uuid[], %s::text, %s::integer, %s::text)",
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor is not None else None,
                limit,
                str(actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
            raise self._unavailable()
        try:
            items = tuple(self._period_lock(item) for item in rows[0]["items"])
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None
        return PeriodLockPage(
            items=items,
            page=LedgerPage(
                next_cursor=(
                    LedgerCursor(str(rows[0]["next_cursor"]))
                    if rows[0].get("next_cursor") is not None
                    else None
                ),
                has_more=bool(rows[0].get("has_more")),
            ),
        )

    def _entry_view(self, value: object) -> LedgerEntryView:
        if not isinstance(value, Mapping):
            raise ValueError("invalid entry")
        raw_lines = value["lines"]
        raw_risks = value.get("riskFlags", [])
        if not isinstance(raw_lines, list) or not isinstance(raw_risks, list):
            raise ValueError("invalid entry payload")
        lines = tuple(
            LedgerLine(
                account=str(line["account"]),
                description=str(line["description"]),
                debit=_money(line["debit"], line.get("currency", "NOK")),
                credit=_money(line["credit"], line.get("currency", "NOK")),
            )
            for line in raw_lines
            if isinstance(line, Mapping)
        )
        risks = tuple(
            LedgerRiskFlag(
                code=LedgerRiskCode(str(flag["code"])),
                account=str(flag["account"]),
            )
            for flag in raw_risks
            if isinstance(flag, Mapping)
        )
        warning_actor = value.get("warningAcceptedBy")
        warning_at = value.get("warningAcceptedAt")
        source_capability = value.get("sourceCapability")
        source_record_id = value.get("sourceRecordId")
        created_at = value.get("createdAt")
        return LedgerEntryView(
            entry_id=LedgerEntryId(str(value["entryId"])),
            company_id=CompanyId(str(value["companyId"])),
            income_year=IncomeYear(int(value["incomeYear"])),
            entry_kind=LedgerEntryKind(str(value["entryKind"])),
            source_capability=(
                LedgerSourceCapability(str(source_capability))
                if source_capability is not None
                else None
            ),
            source_record_id=(
                LedgerSourceRecordId(str(source_record_id))
                if source_record_id is not None
                else None
            ),
            created_at=_timestamp(created_at) if created_at is not None else None,
            memo=str(value["memo"]),
            lines=lines,
            risk_flags=risks,
            warning_accepted_by=_actor(warning_actor) if warning_actor else None,
            warning_accepted_at=_timestamp(warning_at) if warning_at else None,
            posted_by=_actor(value["postedBy"]),
            posted_at=_timestamp(value["postedAt"]),
        )

    def _reconstruction_economic_fact(
        self, value: object
    ) -> ReconstructionEconomicFact:
        if not isinstance(value, Mapping):
            raise ValueError("invalid economic fact")
        raw_lines = value["lines"]
        raw_sources = value["sources"]
        raw_corrections = value["corrections"]
        if not all(
            isinstance(items, list)
            for items in (raw_lines, raw_sources, raw_corrections)
        ) or not all(
            isinstance(item, Mapping)
            for items in (raw_lines, raw_sources, raw_corrections)
            for item in items
        ):
            raise ValueError("invalid economic fact payload")
        lines = tuple(
            LedgerLine(
                account=str(line["account"]),
                description=str(line["description"]),
                debit=_money(line["debit"], line.get("currency", "NOK")),
                credit=_money(line["credit"], line.get("currency", "NOK")),
            )
            for line in raw_lines
        )
        sources = tuple(
            ReconstructionEconomicFactSource(
                role=LedgerFactRole(str(source["role"])),
                capability=LedgerSourceCapability(str(source["capability"])),
                record_id=LedgerSourceRecordId(str(source["recordId"])),
                revision=(
                    int(source["revision"])
                    if source.get("revision") is not None
                    else None
                ),
                fact_sha256=(
                    str(source["factSha256"])
                    if source.get("factSha256") is not None
                    else None
                ),
            )
            for source in raw_sources
        )
        corrections = tuple(
            ReconstructionEconomicFactCorrection(
                original_entry_id=LedgerEntryId(str(correction["originalEntryId"])),
                reversal_entry_id=LedgerEntryId(str(correction["reversalEntryId"])),
                replacement_entry_id=LedgerEntryId(
                    str(correction["replacementEntryId"])
                ),
                reason=str(correction["reason"]),
                corrected_by=_actor(correction["correctedBy"]),
                corrected_at=_timestamp(correction["correctedAt"]),
            )
            for correction in raw_corrections
        )
        rule_version = value.get("ruleVersion")
        return ReconstructionEconomicFact(
            entry_id=LedgerEntryId(str(value["entryId"])),
            event_date=LocalDate(date.fromisoformat(str(value["eventDate"]))),
            entry_kind=LedgerEntryKind(str(value["entryKind"])),
            memo=str(value["memo"]),
            lines=lines,
            correlation_id=CorrelationId(str(value["correlationId"])),
            rule_version=str(rule_version) if rule_version is not None else None,
            sources=sources,
            corrections=corrections,
            posted_by=_actor(value["postedBy"]),
            posted_at=_timestamp(value["postedAt"]),
        )

    def _period_lock(self, value: object) -> PeriodLock:
        if not isinstance(value, Mapping):
            raise ValueError("invalid period lock")
        return PeriodLock(
            period_lock_id=PeriodLockId(str(value["periodLockId"])),
            company_id=CompanyId(str(value["companyId"])),
            income_year=IncomeYear(int(value["incomeYear"])),
            reason=str(value["reason"]),
            locked_by=_actor(value["lockedBy"]),
            locked_at=_timestamp(value["lockedAt"]),
            replayed=False,
        )


class SupabaseLedgerWorkflowTransaction(SupabaseLedgerSession):
    """Ledger and frozen-facade operations bound to one PostgreSQL transaction."""

    def __init__(
        self,
        database_url: str,
        verified: _VerifiedActor,
        connection: psycopg.AsyncConnection[Mapping[str, object]],
    ) -> None:
        super().__init__(database_url, verified)
        self._connection = connection

    async def _database_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        try:
            cursor = await self._connection.execute(query, parameters)
            return list(await cursor.fetchall())
        except psycopg.OperationalError:
            raise self._unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_database_error(str(error)) from None

    async def _one_idempotent_row(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object]:
        rows = await self._database_rows(query, parameters)
        if len(rows) != 1:
            raise self._unavailable()
        return rows[0]

    def _new_year_command(self, command: object) -> NewYearStartCommand:
        if not isinstance(command, NewYearStartCommand):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        return command

    async def claim_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
    ) -> dict[str, object] | None:
        typed = self._new_year_command(command)
        row = await self._one_idempotent_row(
            """
            select backend_system.claim_ledger_workflow_v1(
              %s::text, %s::text, %s::uuid, %s::jsonb, %s::text
            ) as result
            """,
            (
                operation_name,
                str(typed.idempotency_key),
                str(typed.company_id),
                json.dumps(request, separators=(",", ":")),
                str(typed.actor_id.subject),
            ),
        )
        result = row.get("result")
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise self._unavailable()
        return dict(result)

    async def record_legacy_opening_snapshot(
        self,
        command: RecordOpeningSnapshotCommand,
        *,
        ledger_bank_balance: Money,
    ) -> OpeningSnapshotId:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        typed = command
        shareholders = [
            {
                "name": shareholder.name,
                "shareholderKind": shareholder.shareholder_kind,
                "nationalId": shareholder.national_id,
                "orgNumber": shareholder.org_number,
                "shareCount": shareholder.share_count,
            }
            for shareholder in typed.shareholders
        ]
        row = await self._one_idempotent_row(
            """
            select backend_system.record_opening_snapshot_legacy_v1(
              %s::uuid, %s::integer, %s::numeric, %s::numeric,
              %s::integer, %s::numeric, %s::jsonb, %s::text
            ) as setup_id
            """,
            (
                str(typed.company_id),
                int(typed.income_year),
                ledger_bank_balance.amount,
                typed.share_capital.amount,
                typed.share_count,
                typed.nominal_value.amount,
                json.dumps(shareholders, separators=(",", ":")),
                str(typed.actor_id.subject),
            ),
        )
        return OpeningSnapshotId(str(row["setup_id"]))

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
        result: dict[str, object],
    ) -> None:
        typed = self._new_year_command(command)
        await self._one_idempotent_row(
            """
            select backend_system.complete_ledger_workflow_v1(
              %s::text, %s::text, %s::uuid, %s::jsonb, %s::jsonb, %s::text
            ) as completed
            """,
            (
                operation_name,
                str(typed.idempotency_key),
                str(typed.company_id),
                json.dumps(request, separators=(",", ":")),
                json.dumps(result, separators=(",", ":")),
                str(typed.actor_id.subject),
            ),
        )

    def _writer_command(self, command: object, expected: type[LedgerCommand]) -> LedgerCommand:
        if not isinstance(command, expected):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        return command

    async def _prepare_writer(
        self,
        query: str,
        command: LedgerCommand,
    ) -> dict[str, object]:
        row = await self._one_idempotent_row(
            query,
            (
                json.dumps(_writer_payload(command), separators=(",", ":")),
                str(command.actor_id.subject),
            ),
        )
        result = row.get("result")
        if not isinstance(result, Mapping):
            raise self._unavailable()
        return dict(result)

    async def _complete_writer(
        self,
        query: str,
        command: LedgerCommand,
        posted_entry: PostedLedgerEntry | None,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        if posted_entry is not None and (
            posted_entry.company_id != command.company_id
            or posted_entry.income_year != command.income_year
        ):
            raise self._unavailable()
        row = await self._one_idempotent_row(
            query,
            (
                json.dumps(_writer_payload(command), separators=(",", ":")),
                str(posted_entry.entry_id) if posted_entry is not None else None,
                json.dumps(prepared, separators=(",", ":")),
                str(command.actor_id.subject),
            ),
        )
        result = row.get("result")
        if not isinstance(result, Mapping):
            raise self._unavailable()
        return dict(result)

    async def prepare_administrative_cost(
        self, command: object
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordAdministrativeCostCommand)
        return await self._prepare_writer(
            "select backend_system.prepare_administrative_cost_v1(%s::jsonb, %s::text) as result",
            typed,
        )

    async def complete_administrative_cost(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordAdministrativeCostCommand)
        return await self._complete_writer(
            "select backend_system.complete_administrative_cost_v1(%s::jsonb, %s::uuid, %s::jsonb, %s::text) as result",
            typed,
            posted_entry,
            prepared,
        )

    async def prepare_investment_dividend(
        self, command: object
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordInvestmentDividendCommand)
        return await self._prepare_writer(
            "select backend_system.prepare_investment_dividend_v1(%s::jsonb, %s::text) as result",
            typed,
        )

    async def complete_investment_dividend(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordInvestmentDividendCommand)
        return await self._complete_writer(
            "select backend_system.complete_investment_dividend_v1(%s::jsonb, %s::uuid, %s::jsonb, %s::text) as result",
            typed,
            posted_entry,
            prepared,
        )

    async def prepare_shareholder_loan(self, command: object) -> dict[str, object]:
        typed = self._writer_command(command, RecordShareholderLoanCommand)
        return await self._prepare_writer(
            "select backend_system.prepare_shareholder_loan_v1(%s::jsonb, %s::text) as result",
            typed,
        )

    async def complete_shareholder_loan(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordShareholderLoanCommand)
        return await self._complete_writer(
            "select backend_system.complete_shareholder_loan_v1(%s::jsonb, %s::uuid, %s::jsonb, %s::text) as result",
            typed,
            posted_entry,
            prepared,
        )

    async def prepare_tax_settlement(self, command: object) -> dict[str, object]:
        typed = self._writer_command(command, RecordTaxSettlementCommand)
        return await self._prepare_writer(
            "select backend_system.prepare_tax_settlement_v1(%s::jsonb, %s::text) as result",
            typed,
        )

    async def complete_tax_settlement(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordTaxSettlementCommand)
        return await self._complete_writer(
            "select backend_system.complete_tax_settlement_v1(%s::jsonb, %s::uuid, %s::jsonb, %s::text) as result",
            typed,
            posted_entry,
            prepared,
        )

    async def prepare_corporate_decision_finalization(
        self, command: object
    ) -> dict[str, object]:
        typed = self._writer_command(command, FinalizeCorporateDecisionCommand)
        return await self._prepare_writer(
            "select backend_system.prepare_corporate_decision_finalization_v1(%s::jsonb, %s::text) as result",
            typed,
        )

    async def complete_corporate_decision_finalization(
        self,
        command: object,
        posted_entry: PostedLedgerEntry | None,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        typed = self._writer_command(command, FinalizeCorporateDecisionCommand)
        return await self._complete_writer(
            "select backend_system.complete_corporate_decision_finalization_v1(%s::jsonb, %s::uuid, %s::jsonb, %s::text) as result",
            typed,
            posted_entry,
            prepared,
        )

    async def prepare_owner_dividend_payment(
        self, command: object
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordOwnerDividendPaymentCommand)
        return await self._prepare_writer(
            "select backend_system.prepare_owner_dividend_payment_v1(%s::jsonb, %s::text) as result",
            typed,
        )

    async def complete_owner_dividend_payment(
        self,
        command: object,
        posted_entry: PostedLedgerEntry,
        prepared: dict[str, object],
    ) -> dict[str, object]:
        typed = self._writer_command(command, RecordOwnerDividendPaymentCommand)
        return await self._complete_writer(
            "select backend_system.complete_owner_dividend_payment_v1(%s::jsonb, %s::uuid, %s::jsonb, %s::text) as result",
            typed,
            posted_entry,
            prepared,
        )


def compose_ledger_application(
    sessions: LedgerSessionFactory | None = None,
) -> LedgerApplication:
    """Bind the private ledger implementation outside the FastAPI composition root."""

    return LedgerApplication(
        sessions or SupabaseLedgerAdapter.from_environment(),
        LedgerService,
    )
