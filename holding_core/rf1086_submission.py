from __future__ import annotations

from enum import StrEnum

from holding_core.billing import CompanyBillingAccount, production_filing_gate
from holding_core.models import FilingCase
from holding_core.readiness import assess_rf1086_readiness
from holding_core.rf1086 import generate_rf1086
from holding_core.rf1086_codes import production_code_blockers_for_case, production_scope_exclusions_for_case
from holding_core.security import SensitiveAction, StepUpContext, assert_step_up
from holding_core.submission import (
    FilingSubmission,
    mark_blocked_failure,
    mark_submitted,
    prepare_submission,
    register_api_call,
    store_receipt,
)


class Rf1086SubmissionMode(StrEnum):
    TEST = "test"
    PRODUCTION = "production"


def prepare_rf1086_submission(
    case: FilingCase,
    billing_account: CompanyBillingAccount,
    *,
    mode: Rf1086SubmissionMode = Rf1086SubmissionMode.TEST,
    security_context: StepUpContext | None = None,
) -> FilingSubmission:
    submission = prepare_submission(
        filing="aksjonærregisteroppgaven",
        company_id=case.company.org_number,
        income_year=case.company.income_year,
    )
    readiness = assess_rf1086_readiness(case)
    if not readiness.is_ready:
        codes = ", ".join(issue.code for issue in readiness.issues if issue.level == "error")
        return mark_blocked_failure(submission, code="RF1086_READINESS_BLOCKED", message=codes)

    gate = production_filing_gate(billing_account, filing_ready=True)
    if not gate.allowed:
        return mark_blocked_failure(submission, code=gate.status.value, message=gate.message)

    blockers = production_code_blockers_for_case(case)
    if blockers:
        blocked = ", ".join(f"{decision.event}={decision.code_value}" for decision in blockers)
        return mark_blocked_failure(
            submission,
            code="RF1086_CODE_UNVERIFIED",
            message=(
                "Produksjonsinnsending er utilgjengelig fordi offisiell RF-1086-kodeevidens "
                f"ikke er bekreftet for: {blocked}. Talli kan bare simulere til Skatteetaten "
                "har bekreftet kodene i dokumentasjon, kodeliste eller testmiljø."
            ),
        )

    exclusions = production_scope_exclusions_for_case(case)
    if exclusions:
        excluded = ", ".join(f"{decision.event}={decision.code_value}" for decision in exclusions)
        return mark_blocked_failure(
            submission,
            code="RF1086_EVENT_UNSUPPORTED",
            message=(
                "Produksjonsinnsending er bare åpnet for stiftelse/no-activity RF-1086. "
                f"Disse hendelsene er ekskludert fra live filing til Skatteetaten-evidens foreligger: {excluded}. "
                "Talli kan fortsatt simulere og eksportere forhåndsvisning."
            ),
        )

    if mode == Rf1086SubmissionMode.PRODUCTION:
        if security_context is None:
            raise PermissionError("production RF-1086 submission requires security context")
        assert_step_up(SensitiveAction.PRODUCTION_FILING, security_context)

    return submission


def prepare_rf1086_api_calls(
    submission: FilingSubmission,
    case: FilingCase,
    *,
    hovedskjema_id: str = "simulated-hovedskjema-id",
    forsendelse_id: str = "simulated-forsendelse-id",
) -> FilingSubmission:
    documents = generate_rf1086(case)
    base_endpoint = f"/api/aksjonaerregister/v1/{case.company.income_year}"
    submission = register_api_call(
        submission,
        endpoint=f"{base_endpoint}/1086H",
        body={"content_type": "application/xml", "xml": documents.hovedskjema_xml},
    )
    for _, xml in sorted(documents.underskjema_xml.items()):
        submission = register_api_call(
            submission,
            endpoint=f"{base_endpoint}/{hovedskjema_id}/1086U",
            body={"content_type": "application/xml", "xml": xml},
        )
    submission = register_api_call(
        submission,
        endpoint=(
            f"{base_endpoint}/{hovedskjema_id}/bekreft"
            f"?antall_underskjema={len(documents.underskjema_xml)}"
        ),
        body={"antall_underskjema": len(documents.underskjema_xml)},
    )
    return register_api_call(
        submission,
        endpoint=(
            f"{base_endpoint}/forsendelser/{forsendelse_id}/dokumenter"
            "?page=0&size=50"
        ),
        body={"page": 0, "size": 50},
    )


def store_rf1086_feedback_and_receipt(
    submission: FilingSubmission,
    *,
    feedback_document_ids: tuple[str, ...],
    receipt_id: str,
) -> FilingSubmission:
    return store_receipt(mark_submitted(submission, feedback_document_ids=feedback_document_ids), receipt_id=receipt_id)
