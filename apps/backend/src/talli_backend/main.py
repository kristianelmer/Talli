from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter
from talli_backend.modules.company_access.public import (
    AcceptCompanyInvitationRequest,
    AdministerCompanyMembershipRequest,
    CompanyAccessError,
    CompanyAccessGateway,
    CompanyAccessService,
    CompanyCancellationListResponse,
    CompanyCancellationResponse,
    CompanyDeletionReviewResponse,
    CompanyInvitationListResponse,
    CompanyInvitationCommandRequest,
    CompanyInvitationResponse,
    CompanyMembershipListResponse,
    CompanyMembershipResponse,
    CompanyContextResponse,
    CreateCompanyInvitationRequest,
    FinalizeCompanyDeletionRequest,
    InvitationLookup,
    InvitationSideEffectCompletion,
    InvitationSideEffectContinuationList,
    InvitationTokenRequest,
    RequestCompanyCancellationRequest,
    ResumeCompanyCancellationRequest,
    ReviewCompanyDeletionRequest,
)
from talli_backend.modules.system_boundary.public import (
    SYSTEM_BOUNDARY_AVAILABLE,
    SystemBoundaryTransport,
    adapter_for,
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
def create_app(company_access_gateway: CompanyAccessGateway | None = None) -> FastAPI:
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
    company_access_service = CompanyAccessService(gateway)

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

    async def company_access_call(call: Awaitable[object]) -> object:
        try:
            return await call
        except CompanyAccessError as error:
            raise ApiProblem(
                status=error.status,
                code=error.code,
                title=error.title,
                detail=error.detail,
            ) from None

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
        responses=(
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
        tags=["company-access"],
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    )
    async def get_selected_company_context(
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
        company_id: str | None = None,
    ) -> CompanyContextResponse:
        return await company_access_call(
            company_access_service.selected_context(
                bearer_token(credentials),
                company_id=company_id,
            )
        )

    company_access_errors = {
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
    company_access_success = {"headers": {"X-Request-ID": REQUEST_ID_HEADER}}

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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
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
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_AUTH),
    ) -> CompanyCancellationResponse:
        return await company_access_call(
            company_access_service.finalize_deletion(
                bearer_token(credentials), cancellation_id, command
            )
        )

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
