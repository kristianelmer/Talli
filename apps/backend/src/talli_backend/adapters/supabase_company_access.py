"""Supabase Auth plus restricted PostgreSQL adapter for company access."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from talli_backend.modules.company_access.public import (
    AcceptInvitationGatewayCommand,
    AdministerMembershipGatewayCommand,
    CompanyAccessError,
    CompanyAccessGateway,
    CompanyAgreementAcceptanceGatewayCommand,
    CompanyYearAdmissionGatewayCommand,
    CompanyYearEligibilityRecheckGatewayCommand,
    CreateInvitationGatewayCommand,
    FinalizeCompanyDeletionGatewayCommand,
    InvitationIdentityGatewayCommand,
    InvitationMutationGatewayCommand,
    RequestCompanyCancellationGatewayCommand,
    ResendInvitationGatewayCommand,
    ResumeCompanyCancellationGatewayCommand,
    ReviewCompanyDeletionGatewayCommand,
    company_access_adapter,
)


@dataclass(frozen=True)
class SupabaseConfiguration:
    url: str
    anon_key: str
    database_url: str = ""


def _database_contract_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _database_contract_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_database_contract_value(item) for item in value]
    return value


def _database_contract_row(row: Mapping[str, object]) -> Mapping[str, object]:
    """Normalize psycopg-native scalars to the generated JSON contract boundary."""

    return {key: _database_contract_value(value) for key, value in row.items()}


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


@company_access_adapter(CompanyAccessGateway)
class SupabaseCompanyAccessAdapter:
    """Validate Supabase sessions and install their actor in restricted RLS transactions."""

    def __init__(self, configuration: SupabaseConfiguration) -> None:
        self._configuration = configuration
        self._origin = _validated_origin(configuration.url)
        self._anon_key = configuration.anon_key
        self._opener = build_opener(_RejectRedirects)

    @classmethod
    def from_environment(cls) -> SupabaseCompanyAccessAdapter:
        return cls(SupabaseConfiguration(
            url=os.environ.get("SUPABASE_URL", ""),
            anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
            database_url=os.environ.get("TALLI_COMPANY_ACCESS_DATABASE_URL", ""),
        ))

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "apikey": self._anon_key,
            "Authorization": f"Bearer {access_token}",
        }

    async def _auth_user(self, access_token: str) -> object:
        if not self._origin or not self._anon_key:
            raise self._unavailable()

        def send() -> object:
            request = Request(
                f"{self._origin}/auth/v1/user",
                headers=self._auth_headers(access_token),
                method="GET",
            )
            try:
                with self._opener.open(request, timeout=5) as response:
                    return json.loads(response.read())
            except HTTPError as error:
                if error.code in {401, 403}:
                    raise CompanyAccessError(
                        status=401,
                        code="AUTHENTICATION_REQUIRED",
                        title="Authentication required",
                        detail="A valid session is required.",
                    ) from None
                raise self._unavailable() from None
            except (URLError, TimeoutError, json.JSONDecodeError):
                raise self._unavailable() from None

        return await asyncio.to_thread(send)

    async def session_subject(self, access_token: str) -> str:
        response = await self._auth_user(access_token)
        if not isinstance(response, Mapping) or not isinstance(response.get("id"), str):
            raise CompanyAccessError(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            )
        return response["id"]

    async def session_identity(self, access_token: str) -> Mapping[str, object]:
        response = await self._auth_user(access_token)
        if (
            not isinstance(response, Mapping)
            or not isinstance(response.get("id"), str)
            or not isinstance(response.get("email"), str)
        ):
            raise CompanyAccessError(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session with a verified email is required.",
            )
        return {"id": response["id"], "email": response["email"]}

    async def _verified_actor_context(
        self, access_token: str
    ) -> tuple[str, Mapping[str, object]]:
        identity = await self.session_identity(access_token)
        try:
            payload = access_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
        except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise CompanyAccessError(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            ) from None
        actor_id = str(identity["id"])
        if not isinstance(decoded, Mapping) or decoded.get("sub") != actor_id:
            raise CompanyAccessError(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            )
        claims: dict[str, object] = {
            "sub": actor_id,
            "email": str(identity["email"]).strip().lower(),
            "role": "authenticated",
            "aal": decoded.get("aal") if decoded.get("aal") in {"aal1", "aal2"} else "aal1",
        }
        if isinstance(decoded.get("amr"), list):
            claims["amr"] = decoded["amr"]
        return actor_id, claims

    async def _database_rows(
        self,
        access_token: str,
        query: str,
        parameters: tuple[object, ...] = (),
        *,
        role: str = "company_access_executor",
    ) -> list[Mapping[str, object]]:
        if not self._configuration.database_url:
            raise self._unavailable()
        if role not in {"company_access_executor", "company_access_recovery_executor"}:
            raise ValueError("unsupported company-access database role")
        actor_id, claims = await self._verified_actor_context(access_token)

        def execute() -> list[Mapping[str, object]]:
            try:
                with psycopg.connect(
                    self._configuration.database_url,
                    connect_timeout=5,
                    row_factory=dict_row,
                ) as connection, connection.transaction():
                    connection.execute(f"set local role {role}")
                    connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                        (actor_id,),
                    )
                    connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                        (json.dumps(claims, separators=(",", ":")),),
                    )
                    return [
                        _database_contract_row(row)
                        for row in connection.execute(query, parameters).fetchall()
                    ]
            except psycopg.OperationalError:
                raise self._unavailable() from None
            except psycopg.DatabaseError as error:
                message = str(error)
                if "company_access_not_found" in message or "invitation_not_found" in message:
                    invitation = "invitation_not_found" in message
                    raise CompanyAccessError(
                        status=404,
                        code="INVITATION_NOT_FOUND" if invitation else "COMPANY_ACCESS_NOT_FOUND",
                        title="Invitation not found" if invitation else "Company access not found",
                        detail="The requested company access resource was not found.",
                    ) from None
                if "company_access_invalid_request" in message:
                    raise CompanyAccessError(
                        status=422,
                        code="REQUEST_VALIDATION_FAILED",
                        title="Request validation failed",
                        detail="The request did not satisfy the company access policy.",
                    ) from None
                if "company_access_conflict" in message:
                    raise CompanyAccessError(
                        status=409,
                        code="COMPANY_ACCESS_CONFLICT",
                        title="Company access conflict",
                        detail="The company access change conflicts with existing state.",
                    ) from None
                lifecycle_errors = {
                    "cancellation_prerequisite_failed": (
                        "CANCELLATION_PREREQUISITE_FAILED",
                        "Cancellation prerequisite failed",
                        "A current complete company archive export is required.",
                    ),
                    "deletion_review_required": (
                        "DELETION_REVIEW_REQUIRED",
                        "Deletion review required",
                        "An approved deletion review is required.",
                    ),
                }
                for marker, (code, title, detail) in lifecycle_errors.items():
                    if marker in message:
                        raise CompanyAccessError(
                            status=409, code=code, title=title, detail=detail
                        ) from None
                raise self._unavailable() from None

        return await asyncio.to_thread(execute)

    async def memberships(
        self, access_token: str, _subject: str
    ) -> list[Mapping[str, object]]:
        return await self._database_rows(
            access_token,
            """
            select company_id, role, accepted_at
            from public.company_memberships
            where user_id = public.company_access_auth_uid_v1()
              and accepted_at is not null
            """,
        )

    async def companies(self, access_token: str, company_ids: list[str]) -> list[Mapping[str, object]]:
        if not company_ids:
            return []
        return await self._database_rows(
            access_token,
            """
            select id, org_number, name, entity_type, address, postal_code, city,
              status_text, source, created_by, identity_confirmed_at,
              identity_locked_at, created_at
            from public.companies
            where id = any(%s::uuid[])
            order by created_at desc
            """,
            (company_ids,),
        )

    async def agreement_acceptances(
        self, access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        if not company_ids:
            return []
        return await self._database_rows(
            access_token,
            """
            select company_id, business_terms_version, business_terms_effective_date,
              business_terms_path, business_terms_sha256, dpa_version,
              dpa_effective_date, dpa_path, dpa_sha256,
              authority_statement_version, acceptance_method
            from public.customer_agreement_acceptances
            where company_id = any(%s::uuid[])
            order by accepted_at desc
            """,
            (company_ids,),
        )

    async def company_year_access_states(
        self, access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]:
        if not company_ids:
            return []
        return await self._database_rows(
            access_token,
            """
            select a.company_id, a.id as company_year_admission_id,
              a.accounting_year as admitted_accounting_year,
              latest.decision as current_eligibility_decision,
              latest.capability_manifest_version as latest_capability_manifest_version,
              latest.capability_manifest_sha256 as latest_capability_manifest_sha256,
              latest.reason_explanations as eligibility_reason_explanations,
              latest.next_step_code as eligibility_next_step_code,
              latest.next_step as eligibility_next_step,
              latest.consequential_operations_allowed,
              latest.archive_export_available
            from public.company_year_admissions a
            join lateral (
              select e.decision, e.capability_manifest_version,
                e.capability_manifest_sha256, e.reason_explanations,
                e.next_step_code, e.next_step, e.consequential_operations_allowed,
                e.archive_export_available
              from public.company_eligibility_assessments e
              where e.company_id = a.company_id
                and e.accounting_year = a.accounting_year
              order by e.assessed_at desc, e.id desc
              limit 1
            ) latest on true
            where a.company_id = any(%s::uuid[])
            order by a.admitted_at desc
            """,
            (company_ids,),
        )

    async def support_operator(
        self, access_token: str, _subject: str
    ) -> Mapping[str, object] | None:
        rows = await self._database_rows(
            access_token,
            """
            select user_id, role, active
            from public.support_operators
            where user_id = public.company_access_auth_uid_v1() and active
            limit 1
            """,
        )
        return rows[0] if rows else None

    async def search_operator_companies(
        self, access_token: str, query: str
    ) -> list[Mapping[str, object]]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return await self._database_rows(
            access_token,
            """
            select id, org_number, name, entity_type, address, postal_code, city,
              status_text, source, created_by, identity_confirmed_at,
              identity_locked_at, created_at
            from public.companies
            where org_number ilike %s escape '\\'
               or name ilike %s escape '\\'
            order by created_at desc
            limit 10
            """,
            (pattern, pattern),
        )

    async def admit_company_year(
        self, access_token: str, command: CompanyYearAdmissionGatewayCommand
    ) -> Mapping[str, object]:
        company = command.company
        return await self._rpc_row(
            access_token,
            "company_access_admit_company_year",
            {
                "p_operation_id": str(command.operation_id),
                "p_verified_subject": str(command.verified_actor),
                "p_verified_email": command.verified_email,
                "p_org_number": company.org_number,
                "p_name": company.name,
                "p_entity_type": company.entity_type,
                "p_address": company.address,
                "p_postal_code": company.postal_code,
                "p_city": company.city,
                "p_status_text": company.status_text,
                "p_source": company.source,
                "p_accounting_year": command.accounting_year,
                "p_reconstruct_from": command.reconstruct_from,
                "p_public_facts_json": command.public_facts_json,
                "p_public_facts_sha256": command.public_facts_sha256,
                "p_answers_json": command.answers_json,
                "p_answers_sha256": command.answers_sha256,
                "p_capability_manifest_json": command.capability_manifest_json,
                "p_capability_manifest_version": command.capability_manifest_version,
                "p_capability_manifest_sha256": command.capability_manifest_sha256,
                "p_company_year_promise_json": command.company_year_promise_json,
                "p_company_year_promise_sha256": command.company_year_promise_sha256,
                "p_business_terms_version": command.business_terms_version,
                "p_business_terms_effective_date": command.business_terms_effective_date,
                "p_business_terms_path": command.business_terms_path,
                "p_business_terms_sha256": command.business_terms_sha256,
                "p_dpa_version": command.dpa_version,
                "p_dpa_effective_date": command.dpa_effective_date,
                "p_dpa_path": command.dpa_path,
                "p_dpa_sha256": command.dpa_sha256,
                "p_privacy_notice_version": command.privacy_notice_version,
                "p_privacy_notice_effective_date": command.privacy_notice_effective_date,
                "p_privacy_notice_path": command.privacy_notice_path,
                "p_privacy_notice_sha256": command.privacy_notice_sha256,
                "p_authority_statement_version": command.authority_statement_version,
                "p_acceptance_method": command.acceptance_method,
            },
        ) or {}

    async def company_year_admission_replay(
        self, access_token: str, operation_id: str
    ) -> Mapping[str, object] | None:
        rows = await self._database_rows(
            access_token,
            """
            select r.company_id,
              (r.result ->> 'company_year_admission_id')::uuid
                as company_year_admission_id,
              (r.result ->> 'accounting_year')::integer as accounting_year,
              r.result ->> 'reconstruct_from' as reconstruct_from,
              r.result ->> 'capability_manifest_version'
                as capability_manifest_version,
              r.result ->> 'capability_manifest_sha256'
                as capability_manifest_sha256,
              x.customer_org_number as org_number,
              e.public_facts_sha256,
              e.answers,
              x.business_terms_version, x.business_terms_sha256,
              x.dpa_version, x.dpa_sha256,
              x.privacy_notice_version, x.privacy_notice_sha256,
              true as current_agreement_accepted
            from public.company_access_command_receipts r
            join public.company_year_admissions a
              on a.id = (r.result ->> 'company_year_admission_id')::uuid
            join public.company_eligibility_assessments e
              on e.id = a.eligibility_assessment_id
            join public.company_year_acceptances x
              on x.company_year_admission_id = a.id
            where r.actor_id = public.company_access_auth_uid_v1()
              and r.operation_id = %s::uuid
              and r.command_name = 'admit_company_year'
            """,
            (operation_id,),
        )
        return rows[0] if len(rows) == 1 else None

    async def company_year_admission_context(
        self, access_token: str, company_year_admission_id: str, operation_id: str
    ) -> Mapping[str, object] | None:
        rows = await self._database_rows(
            access_token,
            """
            select a.id as company_year_admission_id, a.company_id,
              a.accounting_year, c.org_number,
              a.capability_manifest_version as accepted_capability_manifest_version,
              a.capability_manifest_sha256 as accepted_capability_manifest_sha256,
              a.company_year_promise as accepted_company_year_promise,
              latest.id as latest_assessment_id,
              latest.answers as latest_answers,
              replay.id as replay_assessment_id,
              replay.trigger as replay_trigger,
              replay.decision as replay_decision,
              replay.capability_manifest_version as replay_capability_manifest_version,
              replay.capability_manifest_sha256 as replay_capability_manifest_sha256,
              replay.answers as replay_answers,
              replay.reason_codes as replay_reason_codes,
              replay.reason_explanations as replay_reason_explanations,
              replay.next_step_code as replay_next_step_code,
              replay.next_step as replay_next_step,
              replay.consequential_operations_allowed
                as replay_consequential_operations_allowed,
              replay.archive_export_available as replay_archive_export_available
            from public.company_year_admissions a
            join public.companies c on c.id = a.company_id
            join lateral (
              select e.id, e.answers
              from public.company_eligibility_assessments e
              where e.company_id = a.company_id
                and e.accounting_year = a.accounting_year
              order by e.assessed_at desc, e.id desc
              limit 1
            ) latest on true
            left join lateral (
              select e.id, e.trigger, e.decision,
                e.capability_manifest_version, e.capability_manifest_sha256,
                e.answers, e.reason_codes, e.reason_explanations,
                e.next_step_code, e.next_step,
                e.consequential_operations_allowed, e.archive_export_available
              from public.company_access_command_receipts r
              join public.company_eligibility_assessments e
                on e.id = (r.result ->> 'company_year_eligibility_assessment_id')::uuid
              where r.actor_id = public.company_access_auth_uid_v1()
                and r.operation_id = %s::uuid
                and r.command_name = 'recheck_company_year_eligibility'
                and r.company_id = a.company_id
              limit 1
            ) replay on true
            where a.id = %s::uuid
            """,
            (operation_id, company_year_admission_id),
        )
        return rows[0] if len(rows) == 1 else None

    async def record_company_year_eligibility_recheck(
        self, access_token: str, command: CompanyYearEligibilityRecheckGatewayCommand
    ) -> Mapping[str, object]:
        return await self._rpc_row(
            access_token,
            "company_access_recheck_company_year_eligibility",
            {
                "p_operation_id": str(command.operation_id),
                "p_verified_subject": str(command.verified_actor),
                "p_company_year_admission_id": str(command.company_year_admission_id),
                "p_company_id": str(command.company_id),
                "p_accounting_year": command.accounting_year,
                "p_previous_assessment_id": str(command.previous_assessment_id),
                "p_trigger": command.trigger,
                "p_decision": command.decision,
                "p_capability_manifest_json": command.capability_manifest_json,
                "p_capability_manifest_version": command.capability_manifest_version,
                "p_capability_manifest_sha256": command.capability_manifest_sha256,
                "p_public_facts_json": command.public_facts_json,
                "p_public_facts_sha256": command.public_facts_sha256,
                "p_answers_json": command.answers_json,
                "p_answers_sha256": command.answers_sha256,
                "p_reason_codes": list(command.reason_codes),
                "p_reason_explanations": list(command.reason_explanations),
                "p_next_step_code": command.next_step_code,
                "p_next_step": command.next_step,
                "p_consequential_operations_allowed": (
                    command.consequential_operations_allowed
                ),
                "p_archive_export_available": command.archive_export_available,
            },
        ) or {}

    async def reaccept_agreement(
        self, access_token: str, command: CompanyAgreementAcceptanceGatewayCommand
    ) -> Mapping[str, object]:
        return await self._rpc_row(
            access_token,
            "company_access_reaccept_agreement",
            {
                "p_operation_id": str(command.operation_id),
                "p_company_id": str(command.company_id),
                "p_verified_subject": str(command.verified_actor),
                "p_verified_email": command.verified_email,
                "p_agreement_accepted": True,
                "p_business_terms_version": command.business_terms_version,
                "p_business_terms_effective_date": command.business_terms_effective_date,
                "p_business_terms_path": command.business_terms_path,
                "p_business_terms_sha256": command.business_terms_sha256,
                "p_dpa_version": command.dpa_version,
                "p_dpa_effective_date": command.dpa_effective_date,
                "p_dpa_path": command.dpa_path,
                "p_dpa_sha256": command.dpa_sha256,
                "p_authority_statement_version": command.authority_statement_version,
                "p_acceptance_method": command.acceptance_method,
            },
        ) or {}

    async def invitations(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        return await self._database_rows(
            access_token,
            """
            select id, company_id, invited_email, role, status, expires_at,
              created_at, updated_at
            from public.company_invitations
            where company_id = %s::uuid
            order by updated_at desc
            """,
            (company_id,),
        )

    async def create_invitation(
        self, access_token: str, command: CreateInvitationGatewayCommand
    ) -> Mapping[str, object]:
        return await self._rpc_row(access_token, "company_access_create_invitation", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_invited_email": command.invited_email,
            "p_role": command.role,
            "p_token_hash": command.token_hash,
            "p_acceptance_token": command.acceptance_token,
        }) or {}

    async def lookup_invitation(
        self, access_token: str, command: InvitationIdentityGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token, "company_access_lookup_invitation", {
                "p_token_hash": command.token_hash,
                "p_verified_subject": command.verified_subject,
                "p_verified_email": command.verified_email,
            }
        )

    async def accept_invitation(
        self, access_token: str, command: AcceptInvitationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token, "company_access_accept_invitation", {
                "p_operation_id": command.operation_id,
                "p_token_hash": command.token_hash,
                "p_verified_subject": command.verified_subject,
                "p_verified_email": command.verified_email,
            }
        )

    async def revoke_invitation(
        self, access_token: str, command: InvitationMutationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(access_token, "company_access_revoke_invitation", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_invitation_id": command.invitation_id,
            "p_expected_updated_at": command.expected_updated_at,
        })

    async def resend_invitation(
        self, access_token: str, command: ResendInvitationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(access_token, "company_access_resend_invitation", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_invitation_id": command.invitation_id,
            "p_expected_updated_at": command.expected_updated_at,
            "p_token_hash": command.token_hash,
            "p_acceptance_token": command.acceptance_token,
        })

    async def company_memberships(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        return await self._database_rows(
            access_token,
            """
            select company_id, user_id, role, accepted_at, 'active'::text as state
            from public.company_memberships
            where company_id = %s::uuid
              and role in ('reviewer', 'read_only')
              and accepted_at is not null
            order by created_at asc
            """,
            (company_id,),
        )

    async def administer_membership(
        self, access_token: str, command: AdministerMembershipGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(access_token, "company_access_administer_membership", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_user_id": command.user_id,
            "p_expected_role": command.expected_role,
            "p_role": command.role,
            "p_state": command.state,
        })

    async def pending_invitation_side_effects(
        self, access_token: str
    ) -> list[Mapping[str, object]]:
        return await self._database_rpc_rows(
            access_token,
            "company_access_pending_invitation_side_effects",
            {},
            role="company_access_recovery_executor",
        )

    async def complete_invitation_side_effect(
        self, access_token: str, operation_id: str
    ) -> bool:
        rows = await self._database_rpc_rows(
            access_token,
            "company_access_complete_invitation_side_effect",
            {"p_operation_id": operation_id},
            role="company_access_recovery_executor",
        )
        return bool(rows and next(iter(rows[0].values()), False) is True)

    async def cancellations(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        return await self._database_rpc_rows(
            access_token,
            "company_access_list_cancellations",
            {"p_company_id": company_id},
        )

    async def request_cancellation(
        self, access_token: str, command: RequestCompanyCancellationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_request_cancellation",
            {
                "p_operation_id": command.operation_id,
                "p_company_id": command.company_id,
                "p_income_year": command.income_year,
                "p_reason": command.reason,
            },
        )

    async def review_deletion(
        self, access_token: str, command: ReviewCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_review_deletion",
            {
                "p_operation_id": command.operation_id,
                "p_cancellation_id": command.cancellation_id,
                "p_company_id": command.company_id,
                "p_expected_updated_at": command.expected_updated_at,
                "p_decision": command.decision,
                "p_evidence_reference": command.evidence_reference,
            },
        )

    async def resume_cancellation(
        self, access_token: str, command: ResumeCompanyCancellationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_resume_cancellation",
            {
                "p_operation_id": command.operation_id,
                "p_cancellation_id": command.cancellation_id,
                "p_company_id": command.company_id,
                "p_income_year": command.income_year,
                "p_expected_updated_at": command.expected_updated_at,
            },
        )

    async def finalize_deletion(
        self, access_token: str, command: FinalizeCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_finalize_deletion",
            {
                "p_operation_id": command.operation_id,
                "p_cancellation_id": command.cancellation_id,
                "p_company_id": command.company_id,
                "p_expected_updated_at": command.expected_updated_at,
            },
        )

    async def _rpc_row(
        self,
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        cancellation_command = function_name in {
            "company_access_request_cancellation",
            "company_access_resume_cancellation",
            "company_access_review_deletion",
            "company_access_finalize_deletion",
        }
        if cancellation_command:
            return await self._cancellation_rpc_row(
                access_token, function_name, body
            )
        try:
            response = await self._database_rpc_rows(access_token, function_name, body)
        except CompanyAccessError as error:
            if error.code != "COMPANY_ACCESS_UNAVAILABLE" or "p_operation_id" not in body:
                raise
            # A receipt is definitively absent only after reconciliation has
            # linearized behind the original actor+operation transaction.
            response = await self._database_rpc_rows(access_token, function_name, body)
        if not isinstance(response, list) or not response or not isinstance(response[0], Mapping):
            return None
        return response[0]

    async def _database_rpc_rows(
        self,
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
        *,
        role: str = "company_access_executor",
    ) -> list[Mapping[str, object]]:
        allowed = {
            "company_access_admit_company_year",
            "company_access_recheck_company_year_eligibility",
            "company_access_reaccept_agreement",
            "company_access_create_invitation",
            "company_access_lookup_invitation",
            "company_access_accept_invitation",
            "company_access_revoke_invitation",
            "company_access_resend_invitation",
            "company_access_administer_membership",
            "company_access_pending_invitation_side_effects",
            "company_access_complete_invitation_side_effect",
            "company_access_list_cancellations",
            "company_access_request_cancellation",
            "company_access_resume_cancellation",
            "company_access_review_deletion",
            "company_access_finalize_deletion",
            "company_access_reconcile_cancellation_operation",
        }
        if function_name not in allowed:
            raise ValueError("unsupported company-access database function")
        placeholders = ",".join("%s" for _ in body)
        return await self._database_rows(
            access_token,
            f"select * from public.{function_name}({placeholders})",
            tuple(body.values()),
            role=role,
        )

    async def _cancellation_rpc_row(
        self,
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
    ) -> Mapping[str, object]:
        for attempt in range(2):
            try:
                response = await self._database_rpc_rows(access_token, function_name, body)
            except CompanyAccessError as error:
                if error.code != "COMPANY_ACCESS_UNAVAILABLE":
                    raise
                response = None
            if (
                isinstance(response, list)
                and len(response) == 1
                and isinstance(response[0], Mapping)
            ):
                return response[0]
            state, reconciled = await self._reconcile_cancellation(
                access_token, function_name, body
            )
            if state == "found":
                assert reconciled is not None
                return reconciled
            if attempt == 1:
                raise self._indeterminate_cancellation_reconciliation()
        raise self._indeterminate_cancellation_reconciliation()

    async def _reconcile_cancellation(
        self,
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
    ) -> tuple[str, Mapping[str, object] | None]:
        command_names = {
            "company_access_request_cancellation": "request_cancellation",
            "company_access_resume_cancellation": "resume_cancellation",
            "company_access_review_deletion": "review_deletion",
            "company_access_finalize_deletion": "finalize_deletion",
        }
        reconcile_body = dict(body)
        reconcile_body["p_command_name"] = command_names[function_name]
        ordered = {"p_operation_id": reconcile_body.pop("p_operation_id")}
        ordered["p_command_name"] = reconcile_body.pop("p_command_name")
        ordered.update(reconcile_body)
        response = await self._database_rpc_rows(
            access_token,
            "company_access_reconcile_cancellation_operation",
            ordered,
        )
        if (
            not isinstance(response, list)
            or len(response) != 1
            or not isinstance(response[0], Mapping)
            or set(response[0]) != {"found", "result"}
        ):
            raise self._indeterminate_cancellation_reconciliation()
        row = response[0]
        if row["found"] is False and row["result"] is None:
            return "absent", None
        if row["found"] is not True or not isinstance(row["result"], Mapping):
            raise self._indeterminate_cancellation_reconciliation()
        result = row["result"]
        if function_name == "company_access_review_deletion":
            cancellation = result.get("cancellation")
            review = result.get("review")
            if not isinstance(cancellation, Mapping) or not isinstance(review, Mapping):
                raise self._indeterminate_cancellation_reconciliation()
            return "found", {**cancellation, "review": review}
        return "found", result

    @staticmethod
    def _indeterminate_cancellation_reconciliation() -> CompanyAccessError:
        return CompanyAccessError(
            status=503,
            code="COMPANY_ACCESS_UNAVAILABLE",
            title="Company access unavailable",
            detail="The cancellation operation outcome is still unknown; retry with the same operation ID.",
        )

    @staticmethod
    def _unavailable() -> CompanyAccessError:
        return CompanyAccessError(
            status=503,
            code="COMPANY_ACCESS_UNAVAILABLE",
            title="Company access unavailable",
            detail="Company access is temporarily unavailable.",
        )


__all__ = ["SupabaseCompanyAccessAdapter", "SupabaseConfiguration"]
