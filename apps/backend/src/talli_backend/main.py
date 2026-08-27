from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeVar, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from talli_backend.adapters.brreg_company_registry import BrregCompanyRegistryAdapter
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter
from talli_backend.adapters.supabase_ledger import compose_ledger_application
from talli_backend.application.ledger_workflow import (
    LedgerAuthenticationError,
    LedgerSessionFactory,
    NewYearStartCommand,
)
from talli_backend.modules.company_access.public import (
    AcceptCompanyInvitationRequest,
    AdministerCompanyMembershipRequest,
    CompanyAccessError,
    CompanyAccessGateway,
    CompanyAccessRecordResponse,
    CompanyAccessService,
    CompanyAgreementAcceptanceRequest,
    CompanyAgreementAcceptanceResponse,
    CompanyCancellationListResponse,
    CompanyCancellationResponse,
    CompanyContextResponse,
    CompanyDeletionReviewResponse,
    CompanyYearAdmissionRequest,
    CompanyYearAdmissionResponse,
    CompanyYearEligibilityRecheckRequest,
    CompanyYearEligibilityStateResponse,
    EligibilityDecisionResponse,
    EligibilityDefinitiveRequest,
    EligibilityPrecheckRequest,
    CompanyInvitationCommandRequest,
    CompanyInvitationListResponse,
    CompanyInvitationResponse,
    CompanyMembershipListResponse,
    CompanyMembershipResponse,
    CompanyOnboardingRequest,
    CompanyOnboardingResponse,
    CompanyRegistryGateway,
    CreateCompanyInvitationRequest,
    FinalizeCompanyDeletionRequest,
    InvitationLookup,
    InvitationSideEffectCompletion,
    InvitationSideEffectContinuationList,
    InvitationTokenRequest,
    OperatorCompanySearchResponse,
    OperatorContextResponse,
    RequestCompanyCancellationRequest,
    ResumeCompanyCancellationRequest,
    ReviewCompanyDeletionRequest,
)
from talli_backend.modules.system_boundary.public import (
    SYSTEM_BOUNDARY_AVAILABLE,
    SystemBoundaryTransport,
    adapter_for,
)
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    LedgerCursor,
    LedgerEntryPage,
    LedgerEntryKind,
    LedgerEntryView,
    LedgerError,
    LedgerLine,
    LedgerRiskFlag,
    LedgerRiskCode,
    LedgerSourceRecordId,
    LockPeriodCommand,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostedLedgerEntry,
    PostManualJournalCommand,
)
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningShareholder,
    ShareholderRegisterFilingError,
)
from talli_backend.shared.kernel import (
    CompanyId,
    CorrelationId,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
)

API_VERSION = "v1"
CONTRACT_VERSION = "1.0.0"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REQUEST_ID_HEADER = {
    "description": "Correlation identifier for the request and response.",
    "schema": {"type": "string"},
}
REQUEST_ID_PARAMETER = {
    "description": "Optional caller-provided correlation identifier.",
    "in": "header",
    "name": "X-Request-ID",
    "required": False,
    "schema": {"type": "string"},
}
BEARER_AUTH = HTTPBearer(scheme_name="bearerAuth", auto_error=False)
BEARER_DEPENDENCY = Depends(BEARER_AUTH)
ResponseT = TypeVar("ResponseT")


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class TransportModel(BaseModel):
    model_config = ConfigDict(alias_generator=lambda name: _to_camel(name), populate_by_name=True)


class SystemBoundaryStatus(TransportModel):
    api_version: str
    service: str
    status: Literal["AVAILABLE"]


class ProblemDetails(TransportModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str


class StrictTransportModel(TransportModel):
    model_config = ConfigDict(
        alias_generator=lambda name: _to_camel(name),
        populate_by_name=True,
        extra="forbid",
    )


class LedgerMoneyWire(StrictTransportModel):
    amount: str = Field(
        max_length=64,
        pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$",
    )
    currency: Literal["NOK"]

    def to_domain(self) -> Money:
        return Money.nok(self.amount)


class LedgerLineWire(StrictTransportModel):
    account: str = Field(max_length=16)
    description: str = Field(max_length=500)
    debit: LedgerMoneyWire
    credit: LedgerMoneyWire

    def to_domain(self) -> LedgerLine:
        return LedgerLine(
            account=self.account,
            description=self.description,
            debit=self.debit.to_domain(),
            credit=self.credit.to_domain(),
        )


class LedgerCompanyYearWire(StrictTransportModel):
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)


class NewYearShareholderWire(StrictTransportModel):
    name: str = Field(min_length=1, max_length=255)
    shareholder_kind: Literal["norwegian_person", "norwegian_company"]
    national_id: str | None = Field(default=None, pattern=r"^\d{11}$")
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")
    share_count: int = Field(ge=0, le=2_147_483_647)


class NewYearStartWire(LedgerCompanyYearWire):
    bank_balance: LedgerMoneyWire
    share_capital: LedgerMoneyWire
    share_count: int = Field(gt=0, le=2_147_483_647)
    nominal_value: LedgerMoneyWire
    shareholders: list[NewYearShareholderWire] = Field(min_length=1, max_length=100)


class LedgerAdministrativeCostWire(LedgerCompanyYearWire):
    bank_transaction_id: str = Field(min_length=1, max_length=255)
    category: AdministrativeCostCategory
    payee: str = Field(min_length=1, max_length=255)
    amount: LedgerMoneyWire
    paid_date: date
    document_id: str | None = Field(default=None, min_length=1, max_length=255)


class LedgerManualJournalWire(LedgerCompanyYearWire):
    memo: str = Field(min_length=1, max_length=500)
    lines: list[LedgerLineWire] = Field(min_length=2, max_length=100)
    warning_accepted: bool


class LedgerLockPeriodWire(LedgerCompanyYearWire):
    reason: str = Field(min_length=1, max_length=500)


class LedgerPostedEntryWire(TransportModel):
    entry_id: str
    company_id: str
    income_year: int
    entry_kind: LedgerEntryKind
    posted_at: datetime
    replayed: bool


class NewYearOpeningEntryWire(TransportModel):
    entry_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    entry_kind: Literal["OPENING_BALANCE"]
    posted_at: datetime
    replayed: bool


class AdministrativeCostEntryWire(TransportModel):
    entry_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    entry_kind: Literal["ADMINISTRATIVE_COST"]
    posted_at: datetime
    replayed: bool


class NewYearStartResultWire(TransportModel):
    setup_id: UUID
    posted_entry: NewYearOpeningEntryWire


class LedgerRiskFlagWire(TransportModel):
    code: LedgerRiskCode
    account: str


class LedgerEntryViewWire(TransportModel):
    entry_id: str
    company_id: str
    income_year: int
    entry_kind: LedgerEntryKind
    memo: str
    lines: list[LedgerLineWire]
    risk_flags: list[LedgerRiskFlagWire]
    warning_accepted_by: str | None
    warning_accepted_at: datetime | None
    posted_by: str
    posted_at: datetime


class LedgerPeriodLockWire(TransportModel):
    period_lock_id: str
    company_id: str
    income_year: int
    reason: str
    locked_by: str
    locked_at: datetime
    replayed: bool


class LedgerPageWire(TransportModel):
    next_cursor: str | None
    has_more: bool


class LedgerEntryPageWire(TransportModel):
    items: list[LedgerEntryViewWire]
    page: LedgerPageWire


class LedgerPeriodLockPageWire(TransportModel):
    items: list[LedgerPeriodLockWire]
    page: LedgerPageWire


def _money_wire(value: Money) -> LedgerMoneyWire:
    return LedgerMoneyWire(amount=format(value.amount, "f"), currency=value.currency.value)


def _line_wire(value: LedgerLine) -> LedgerLineWire:
    return LedgerLineWire(
        account=value.account,
        description=value.description,
        debit=_money_wire(value.debit),
        credit=_money_wire(value.credit),
    )


def _risk_wire(value: LedgerRiskFlag) -> LedgerRiskFlagWire:
    return LedgerRiskFlagWire(code=value.code, account=value.account)


def _posted_wire(value: PostedLedgerEntry) -> LedgerPostedEntryWire:
    return LedgerPostedEntryWire(
        entry_id=str(value.entry_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        entry_kind=value.entry_kind,
        posted_at=value.posted_at.value,
        replayed=value.replayed,
    )


def _lock_wire(value: PeriodLock) -> LedgerPeriodLockWire:
    return LedgerPeriodLockWire(
        period_lock_id=str(value.period_lock_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        reason=value.reason,
        locked_by=str(value.locked_by.subject),
        locked_at=value.locked_at.value,
        replayed=value.replayed,
    )


def _entry_view_wire(value: LedgerEntryView) -> LedgerEntryViewWire:
    return LedgerEntryViewWire(
        entry_id=str(value.entry_id),
        company_id=str(value.company_id),
        income_year=int(value.income_year),
        entry_kind=value.entry_kind,
        memo=value.memo,
        lines=[_line_wire(line) for line in value.lines],
        risk_flags=[_risk_wire(flag) for flag in value.risk_flags],
        warning_accepted_by=(
            str(value.warning_accepted_by.subject)
            if value.warning_accepted_by is not None
            else None
        ),
        warning_accepted_at=(
            value.warning_accepted_at.value
            if value.warning_accepted_at is not None
            else None
        ),
        posted_by=str(value.posted_by.subject),
        posted_at=value.posted_at.value,
    )


class ApiProblem(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


def _request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID", "")
    return candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _request_id(request)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", _request_id(request))
    problem = ProblemDetails(
        type=f"https://talli.no/problems/{code.lower().replace('_', '-')}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(by_alias=True),
        media_type="application/problem+json",
        headers={"X-Request-ID": request_id},
    )


@adapter_for(SystemBoundaryTransport)
def create_app(
    company_access_gateway: CompanyAccessGateway | None = None,
    company_registry_gateway: CompanyRegistryGateway | None = None,
    ledger_session_factory: LedgerSessionFactory | None = None,
) -> FastAPI:
    application = FastAPI(
        title="Talli API",
        summary="Talli web-to-backend production boundary",
        version=CONTRACT_VERSION,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    application.add_middleware(RequestIdMiddleware)
    gateway = (
        company_access_gateway
        if company_access_gateway is not None
        else SupabaseCompanyAccessAdapter.from_environment()
    )
    company_access_service = CompanyAccessService(
        gateway,
        company_registry_gateway or BrregCompanyRegistryAdapter.from_environment(),
    )
    ledger_application = compose_ledger_application(ledger_session_factory)

    def bearer_token(
        credentials: HTTPAuthorizationCredentials | None,
    ) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            )
        return credentials.credentials

    async def company_access_call(call: Awaitable[ResponseT]) -> ResponseT:
        try:
            return await call
        except CompanyAccessError as error:
            raise ApiProblem(
                status=error.status,
                code=error.code,
                title=error.title,
                detail=error.detail,
            ) from None

    async def ledger_call(call: Callable[[], Awaitable[ResponseT]]) -> ResponseT:
        try:
            return await call()
        except LedgerAuthenticationError:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            ) from None
        except LedgerError as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422,
                ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409,
                ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409,
                ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            raise ApiProblem(
                status=statuses[error.category],
                code=error.code,
                title="Ledger request failed",
                detail=error.message or "The ledger request could not be completed.",
            ) from None
        except ShareholderRegisterFilingError as error:
            statuses = {
                ErrorCategory.INVALID_INPUT: 422,
                ErrorCategory.NOT_FOUND: 404,
                ErrorCategory.CONFLICT: 409,
                ErrorCategory.FORBIDDEN: 403,
                ErrorCategory.PRECONDITION_FAILED: 409,
                ErrorCategory.DEPENDENCY_UNAVAILABLE: 503,
            }
            raise ApiProblem(
                status=statuses[error.category],
                code=error.code,
                title="New-year request failed",
                detail=error.message or "The opening snapshot could not be recorded.",
            ) from None

    def ledger_input(factory: Callable[[], ResponseT]) -> ResponseT:
        try:
            return factory()
        except (TypeError, ValueError, ShareholderRegisterFilingError):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT") from None

    @application.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, error: ApiProblem) -> JSONResponse:
        return _problem_response(
            request,
            status=error.status,
            code=error.code,
            title=error.title,
            detail=error.detail,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _problem_response(
            request,
            status=422,
            code="REQUEST_VALIDATION_FAILED",
            title="Request validation failed",
            detail="The request did not satisfy the API contract.",
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        definitions = {
            404: ("RESOURCE_NOT_FOUND", "Resource not found", "The requested resource does not exist."),
            405: ("METHOD_NOT_ALLOWED", "Method not allowed", "The request method is not supported."),
        }
        code, title, detail = definitions.get(
            error.status_code,
            ("HTTP_ERROR", "Request failed", "The request could not be completed."),
        )
        return _problem_response(
            request,
            status=error.status_code,
            code=code,
            title=title,
            detail=detail,
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _error: Exception) -> JSONResponse:
        return _problem_response(
            request,
            status=500,
            code="INTERNAL_SERVER_ERROR",
            title="Internal server error",
            detail="An unexpected error occurred.",
        )

    @application.get(
        "/api/v1/system-boundary/tracer",
        operation_id="systemBoundaryGetTracerStatus",
        response_model=SystemBoundaryStatus,
        responses={
            200: {
                "description": "Successful Response",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            },
            500: {
                "description": "An unexpected backend failure occurred.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                "content": {
                    "application/problem+json": {
                        "schema": ProblemDetails.model_json_schema(by_alias=True)
                    }
                },
            },
            503: {
                "description": "The backend boundary is temporarily unavailable.",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                "content": {
                    "application/problem+json": {
                        "schema": ProblemDetails.model_json_schema(by_alias=True)
                    }
                },
            }
        },
        tags=["system-boundary"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_system_boundary_status() -> SystemBoundaryStatus:
        return SystemBoundaryStatus(
            api_version=API_VERSION,
            service="talli-backend",
            status=SYSTEM_BOUNDARY_AVAILABLE,
        )

    @application.get(
        "/api/v1/company-access/context",
        operation_id="companyAccessGetSelectedContext",
        response_model=CompanyContextResponse,
        responses=cast(
            dict[int | str, dict[str, Any]],
            (
            {
                200: {
                    "description": "Selected company context.",
                    "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                }
            }
            | {
                status: {
                    "description": "Company context request failed.",
                    "headers": {"X-Request-ID": REQUEST_ID_HEADER},
                    "content": {
                        "application/problem+json": {
                            "schema": ProblemDetails.model_json_schema(by_alias=True)
                        }
                    },
                }
                for status in (401, 403, 404, 422, 503)
            }
            ),
        ),
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_selected_company_context(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
        company_id: str | None = None,
    ) -> CompanyContextResponse:
        return await company_access_call(
            company_access_service.selected_context(
                bearer_token(credentials),
                company_id=company_id,
            )
        )

    company_access_errors: Any = {
        status: {
            "description": "Company access request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (401, 403, 404, 409, 422, 503)
    }
    company_access_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    @application.post(
        "/api/v1/company-access/eligibility/precheck",
        operation_id="companyAccessEligibilityPrecheck",
        response_model=EligibilityDecisionResponse,
        responses={
            200: {
                "description": "Provisional public-company eligibility result",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (404, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def eligibility_precheck(
        command: EligibilityPrecheckRequest,
    ) -> EligibilityDecisionResponse:
        return await company_access_call(
            company_access_service.eligibility_precheck(command)
        )

    @application.post(
        "/api/v1/company-access/eligibility/definitive",
        operation_id="companyAccessEligibilityDefinitive",
        response_model=EligibilityDecisionResponse,
        responses={
            200: {
                "description": "Definitive company-year eligibility result",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (409, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def eligibility_definitive(
        command: EligibilityDefinitiveRequest,
    ) -> EligibilityDecisionResponse:
        return await company_access_call(
            company_access_service.eligibility_definitive(command)
        )

    @application.post(
        "/api/v1/company-access/company-year-admissions",
        operation_id="companyAccessAdmitCompanyYear",
        response_model=CompanyYearAdmissionResponse,
        status_code=201,
        responses={
            201: {
                "description": "Company year admitted",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (401, 409, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def admit_company_year(
        command: CompanyYearAdmissionRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyYearAdmissionResponse:
        return await company_access_call(
            company_access_service.admit_company_year(
                bearer_token(credentials), command
            )
        )

    @application.post(
        (
            "/api/v1/company-access/company-year-admissions/"
            "{company_year_admission_id}/eligibility-rechecks"
        ),
        operation_id="companyAccessRecheckCompanyYearEligibility",
        response_model=CompanyYearEligibilityStateResponse,
        status_code=201,
        responses={
            201: {
                "description": "Current eligibility gate appended",
                "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            }
        }
        | {status: company_access_errors[status] for status in (401, 404, 409, 422, 503)},
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def recheck_company_year_eligibility(
        company_year_admission_id: UUID,
        command: CompanyYearEligibilityRecheckRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyYearEligibilityStateResponse:
        return await company_access_call(
            company_access_service.recheck_company_year_eligibility(
                bearer_token(credentials), company_year_admission_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/onboarding",
        operation_id="companyAccessOnboardCompany",
        response_model=CompanyOnboardingResponse,
        status_code=201,
        deprecated=True,
        responses={
            201: {"description": "Company and current agreement evidence created atomically."}
            | company_access_success
        }
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def onboard_company(
        command: CompanyOnboardingRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyOnboardingResponse:
        return await company_access_call(
            company_access_service.onboard_company(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/agreements/reaccept",
        operation_id="companyAccessReacceptAgreement",
        response_model=CompanyAgreementAcceptanceResponse,
        responses={
            200: {"description": "Current agreement evidence accepted."}
            | company_access_success
        }
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def reaccept_company_agreement(
        command: CompanyAgreementAcceptanceRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyAgreementAcceptanceResponse:
        return await company_access_call(
            company_access_service.reaccept_agreement(
                bearer_token(credentials), command
            )
        )

    @application.get(
        "/api/v1/company-access/companies/{company_id}",
        operation_id="companyAccessGetCompanyRecord",
        response_model=CompanyAccessRecordResponse,
        responses={200: {"description": "Accepted-member company record."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_company_access_record(
        company_id: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyAccessRecordResponse:
        return await company_access_call(
            company_access_service.company_record(
                bearer_token(credentials), company_id=company_id
            )
        )

    @application.get(
        "/api/v1/company-access/operator-context",
        operation_id="companyAccessGetOperatorContext",
        response_model=OperatorContextResponse,
        responses={200: {"description": "Active operator context."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_company_access_operator_context(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OperatorContextResponse:
        return await company_access_call(
            company_access_service.operator_context(bearer_token(credentials))
        )

    @application.get(
        "/api/v1/company-access/operator-companies",
        operation_id="companyAccessSearchOperatorCompanies",
        response_model=OperatorCompanySearchResponse,
        responses={200: {"description": "Bounded operator company search."} | company_access_success}
        | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def search_company_access_operator_companies(
        query: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> OperatorCompanySearchResponse:
        return await company_access_call(
            company_access_service.search_operator_companies(
                bearer_token(credentials), query=query
            )
        )

    @application.get(
        "/api/v1/company-access/invitations",
        operation_id="companyAccessListInvitations",
        response_model=CompanyInvitationListResponse,
        responses={200: {"description": "Company invitations."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_company_invitations(
        company_id: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationListResponse:
        return await company_access_call(
            company_access_service.list_invitations(
                bearer_token(credentials), company_id=company_id
            )
        )

    @application.post(
        "/api/v1/company-access/invitations",
        operation_id="companyAccessCreateInvitation",
        response_model=CompanyInvitationResponse,
        status_code=201,
        responses={201: {"description": "Company invitation created."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def create_company_invitation(
        command: CreateCompanyInvitationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationResponse:
        return await company_access_call(
            company_access_service.invite(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/invitations/lookup",
        operation_id="companyAccessLookupInvitation",
        response_model=InvitationLookup,
        responses={200: {"description": "Available invitation."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def lookup_company_invitation(
        command: InvitationTokenRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvitationLookup:
        return await company_access_call(
            company_access_service.lookup_invitation(
                bearer_token(credentials), token=command.token
            )
        )

    @application.post(
        "/api/v1/company-access/invitations/accept",
        operation_id="companyAccessAcceptInvitation",
        response_model=CompanyMembershipResponse,
        responses={200: {"description": "Invitation accepted."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def accept_company_invitation(
        command: AcceptCompanyInvitationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyMembershipResponse:
        return await company_access_call(
            company_access_service.accept_invitation(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/invitations/{invitation_id}/revoke",
        operation_id="companyAccessRevokeInvitation",
        response_model=CompanyInvitationResponse,
        responses={200: {"description": "Invitation revoked."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def revoke_company_invitation(
        invitation_id: UUID,
        command: CompanyInvitationCommandRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationResponse:
        return await company_access_call(
            company_access_service.revoke_invitation(
                bearer_token(credentials),
                invitation_id=invitation_id,
                command=command,
            )
        )

    @application.post(
        "/api/v1/company-access/invitations/{invitation_id}/resend",
        operation_id="companyAccessResendInvitation",
        response_model=CompanyInvitationResponse,
        responses={200: {"description": "Invitation resent."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def resend_company_invitation(
        invitation_id: UUID,
        command: CompanyInvitationCommandRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyInvitationResponse:
        return await company_access_call(
            company_access_service.resend_invitation(
                bearer_token(credentials),
                invitation_id=invitation_id,
                command=command,
            )
        )

    @application.get(
        "/api/v1/company-access/invitation-side-effects/pending",
        operation_id="companyAccessListPendingInvitationSideEffects",
        response_model=InvitationSideEffectContinuationList,
        responses={200: {"description": "Pending invitation side effects."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_pending_invitation_side_effects(
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvitationSideEffectContinuationList:
        return await company_access_call(
            company_access_service.pending_invitation_side_effects(
                bearer_token(credentials)
            )
        )

    @application.post(
        "/api/v1/company-access/invitation-side-effects/{operation_id}/complete",
        operation_id="companyAccessCompleteInvitationSideEffect",
        response_model=InvitationSideEffectCompletion,
        responses={200: {"description": "Invitation side effects completed."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def complete_invitation_side_effect(
        operation_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> InvitationSideEffectCompletion:
        return await company_access_call(
            company_access_service.complete_invitation_side_effect(
                bearer_token(credentials), operation_id
            )
        )

    @application.get(
        "/api/v1/company-access/memberships",
        operation_id="companyAccessListMemberships",
        response_model=CompanyMembershipListResponse,
        responses={200: {"description": "Company memberships."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_company_memberships(
        company_id: str,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyMembershipListResponse:
        return await company_access_call(
            company_access_service.list_memberships(
                bearer_token(credentials), company_id=company_id
            )
        )

    @application.patch(
        "/api/v1/company-access/memberships/{user_id}",
        operation_id="companyAccessAdministerMembership",
        response_model=CompanyMembershipResponse,
        responses={200: {"description": "Membership changed."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def administer_company_membership(
        user_id: UUID,
        command: AdministerCompanyMembershipRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyMembershipResponse:
        return await company_access_call(
            company_access_service.administer_membership(
                bearer_token(credentials),
                user_id=user_id,
                command=command,
            )
        )

    @application.get(
        "/api/v1/company-access/cancellations",
        operation_id="companyAccessListCancellations",
        response_model=CompanyCancellationListResponse,
        responses={200: {"description": "Visible company cancellation lifecycle records."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_company_cancellations(
        company_id: UUID,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationListResponse:
        return await company_access_call(
            company_access_service.list_cancellations(
                bearer_token(credentials), company_id=str(company_id)
            )
        )

    @application.post(
        "/api/v1/company-access/cancellations",
        operation_id="companyAccessRequestCancellation",
        response_model=CompanyCancellationResponse,
        status_code=201,
        responses={201: {"description": "Cancellation entered retention hold."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def request_company_cancellation(
        command: RequestCompanyCancellationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.request_cancellation(bearer_token(credentials), command)
        )

    @application.post(
        "/api/v1/company-access/cancellations/{cancellation_id}/reviews",
        operation_id="companyAccessReviewDeletion",
        response_model=CompanyDeletionReviewResponse,
        responses={200: {"description": "Append-only deletion review recorded."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def review_company_deletion(
        cancellation_id: UUID,
        command: ReviewCompanyDeletionRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyDeletionReviewResponse:
        return await company_access_call(
            company_access_service.review_deletion(
                bearer_token(credentials), cancellation_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/cancellations/{cancellation_id}/resume",
        operation_id="companyAccessResumeCancellation",
        response_model=CompanyCancellationResponse,
        responses={200: {"description": "Legacy cancellation advanced after authoritative archive export."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def resume_company_cancellation(
        cancellation_id: UUID,
        command: ResumeCompanyCancellationRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.resume_cancellation(
                bearer_token(credentials), cancellation_id, command
            )
        )

    @application.post(
        "/api/v1/company-access/cancellations/{cancellation_id}/finalize",
        operation_id="companyAccessFinalizeDeletion",
        response_model=CompanyCancellationResponse,
        responses={200: {"description": "Deletion lifecycle finalized without physical business-data deletion."} | company_access_success} | company_access_errors,
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def finalize_company_deletion(
        cancellation_id: UUID,
        command: FinalizeCompanyDeletionRequest,
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.finalize_deletion(
                bearer_token(credentials), cancellation_id, command
            )
        )

    ledger_errors: Any = {
        status: {
            "description": "Ledger request failed.",
            "headers": {"X-Request-ID": REQUEST_ID_HEADER},
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(by_alias=True)
                }
            },
        }
        for status in (400, 401, 403, 404, 409, 422, 503)
    }
    ledger_success: dict[str, Any] = {
        "headers": {"X-Request-ID": REQUEST_ID_HEADER}
    }

    def ledger_correlation(request: Request) -> CorrelationId:
        return CorrelationId(request.state.request_id)

    @application.get(
        "/api/v1/ledger/entries",
        operation_id="ledgerListEntries",
        response_model=LedgerEntryPageWire,
        responses={200: {"description": "Authorized ledger-entry page."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_ledger_entries(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: int = Query(default=50, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerEntryPageWire:
        async def execute() -> LedgerEntryPageWire:
            session = await ledger_application.session(bearer_token(credentials))
            page: LedgerEntryPage = await session.list_entries(
                actor_id=session.actor_id,
                company_ids=ledger_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=ledger_correlation(request),
                cursor=ledger_input(lambda: LedgerCursor(cursor)) if cursor else None,
                limit=limit,
            )
            return LedgerEntryPageWire(
                items=[_entry_view_wire(item) for item in page.items],
                page=LedgerPageWire(
                    next_cursor=(
                        str(page.page.next_cursor)
                        if page.page.next_cursor is not None
                        else None
                    ),
                    has_more=page.page.has_more,
                ),
            )

        return await ledger_call(execute)

    @application.get(
        "/api/v1/ledger/period-locks",
        operation_id="ledgerListPeriodLocks",
        response_model=LedgerPeriodLockPageWire,
        responses={200: {"description": "Authorized period-lock page."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def list_ledger_period_locks(
        request: Request,
        company_id: Annotated[
            list[UUID], Query(alias="companyId", min_length=1, max_length=100)
        ],
        cursor: Annotated[str | None, Query(max_length=4096)] = None,
        limit: int = Query(default=50, ge=1, le=100),
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerPeriodLockPageWire:
        async def execute() -> LedgerPeriodLockPageWire:
            session = await ledger_application.session(bearer_token(credentials))
            page: PeriodLockPage = await session.list_period_locks(
                actor_id=session.actor_id,
                company_ids=ledger_input(
                    lambda: tuple(CompanyId(str(value)) for value in company_id)
                ),
                correlation_id=ledger_correlation(request),
                cursor=ledger_input(lambda: LedgerCursor(cursor)) if cursor else None,
                limit=limit,
            )
            return LedgerPeriodLockPageWire(
                items=[_lock_wire(item) for item in page.items],
                page=LedgerPageWire(
                    next_cursor=(
                        str(page.page.next_cursor)
                        if page.page.next_cursor is not None
                        else None
                    ),
                    has_more=page.page.has_more,
                ),
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/new-year-starts",
        operation_id="ledgerStartNewYear",
        response_model=NewYearStartResultWire,
        status_code=201,
        responses={201: {"description": "Company year started atomically."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def start_new_year(
        request: Request,
        command: NewYearStartWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> NewYearStartResultWire:
        async def execute() -> NewYearStartResultWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: NewYearStartCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    bank_balance=command.bank_balance.to_domain(),
                    share_capital=command.share_capital.to_domain(),
                    share_count=command.share_count,
                    nominal_value=command.nominal_value.to_domain(),
                    shareholders=tuple(
                        OpeningShareholder(
                            name=shareholder.name,
                            shareholder_kind=shareholder.shareholder_kind,
                            national_id=shareholder.national_id,
                            org_number=shareholder.org_number,
                            share_count=shareholder.share_count,
                        )
                        for shareholder in command.shareholders
                    ),
                )
            )
            result = await session.start_new_year(domain_command)
            return NewYearStartResultWire(
                setup_id=str(result.setup_id),
                posted_entry=NewYearOpeningEntryWire(
                    entry_id=str(result.posted_entry.entry_id),
                    company_id=str(result.posted_entry.company_id),
                    income_year=int(result.posted_entry.income_year),
                    entry_kind="OPENING_BALANCE",
                    posted_at=result.posted_entry.posted_at.value,
                    replayed=result.posted_entry.replayed,
                ),
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/administrative-costs",
        operation_id="ledgerPostAdministrativeCost",
        response_model=AdministrativeCostEntryWire,
        status_code=201,
        responses={201: {"description": "Administrative cost posted."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def post_ledger_administrative_cost(
        request: Request,
        command: LedgerAdministrativeCostWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> AdministrativeCostEntryWire:
        async def execute() -> AdministrativeCostEntryWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: PostAdministrativeCostCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    bank_transaction_id=LedgerSourceRecordId(command.bank_transaction_id),
                    category=command.category,
                    payee=command.payee,
                    amount=command.amount.to_domain(),
                    paid_date=LocalDate(command.paid_date),
                    document_id=(
                        LedgerSourceRecordId(command.document_id)
                        if command.document_id is not None
                        else None
                    ),
                )
            )
            result = await session.post_administrative_cost(domain_command)
            if (
                result.company_id != domain_command.company_id
                or result.income_year != domain_command.income_year
                or result.entry_kind is not LedgerEntryKind.ADMINISTRATIVE_COST
            ):
                raise LedgerError.unavailable()
            return AdministrativeCostEntryWire(
                entry_id=UUID(str(result.entry_id)),
                company_id=UUID(str(result.company_id)),
                income_year=int(result.income_year),
                entry_kind=result.entry_kind.value,
                posted_at=result.posted_at.value,
                replayed=result.replayed,
            )

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/manual-journals",
        operation_id="ledgerPostManualJournal",
        response_model=LedgerPostedEntryWire,
        status_code=201,
        responses={201: {"description": "Manual journal posted."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def post_ledger_manual_journal(
        request: Request,
        command: LedgerManualJournalWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerPostedEntryWire:
        async def execute() -> LedgerPostedEntryWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: PostManualJournalCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    memo=command.memo,
                    lines=tuple(line.to_domain() for line in command.lines),
                    warning_accepted=command.warning_accepted,
                )
            )
            result = await session.post_manual_journal(domain_command)
            return _posted_wire(result)

        return await ledger_call(execute)

    @application.post(
        "/api/v1/ledger/period-locks",
        operation_id="ledgerLockPeriod",
        response_model=LedgerPeriodLockWire,
        status_code=201,
        responses={201: {"description": "Period locked."} | ledger_success}
        | ledger_errors,
        tags=["ledger"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def lock_ledger_period(
        request: Request,
        command: LedgerLockPeriodWire,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=255)
        ],
        credentials: HTTPAuthorizationCredentials | None = BEARER_DEPENDENCY,
    ) -> LedgerPeriodLockWire:
        async def execute() -> LedgerPeriodLockWire:
            session = await ledger_application.session(bearer_token(credentials))
            domain_command = ledger_input(
                lambda: LockPeriodCommand(
                    company_id=CompanyId(str(command.company_id)),
                    actor_id=session.actor_id,
                    correlation_id=ledger_correlation(request),
                    idempotency_key=IdempotencyKey(idempotency_key),
                    income_year=IncomeYear(command.income_year),
                    reason=command.reason,
                )
            )
            result = await session.lock_period(domain_command)
            return _lock_wire(result)

        return await ledger_call(execute)

    @application.get("/health/live", include_in_schema=False)
    async def liveness() -> JSONResponse:
        return JSONResponse(
            {"status": "alive"},
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/health/ready", include_in_schema=False)
    async def readiness() -> JSONResponse:
        return JSONResponse(
            {"status": "ready"},
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/api/v1/openapi.json", include_in_schema=False)
    async def served_openapi() -> Response:
        from talli_backend.openapi import serialize_openapi

        return Response(
            content=serialize_openapi(application),
            media_type="application/vnd.oai.openapi+json;version=3.1",
            headers={"Cache-Control": "no-store"},
        )

    return application


app = create_app()
