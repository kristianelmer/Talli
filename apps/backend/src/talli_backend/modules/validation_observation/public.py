"""Fail-closed, side-effect-only port for invited validation observation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol, TypeVar
from uuid import UUID


ValidationObservationMode = Literal["off", "invited-pilot"]
ValidationTask = Literal[
    "eligibility_precheck",
    "eligibility_definitive",
    "company_year_admission",
    "opening_reconstruction",
    "bank_connection",
    "bank_import",
    "bookkeeping",
    "year_close",
    "shareholder_register_filing",
    "company_tax_filing",
    "annual_accounts_filing",
    "archive_export",
]
ValidationState = Literal["started", "completed", "failed", "blocked"]
ValidationStage = Literal[
    "eligibility",
    "onboarding",
    "reconstruction",
    "banking",
    "bookkeeping",
    "year_close",
    "shareholder_register",
    "company_tax",
    "annual_accounts",
    "archive",
]
ValidationReason = Literal[
    "none",
    "unsupported_boundary",
    "missing_evidence",
    "authorization_required",
    "provider_unavailable",
    "technical_failure",
    "difference_detected",
    "participant_withdrew",
]
ValidationInterventionType = Literal[
    "none", "navigation_help", "evidence_help", "technical_support"
]
ValidationDifferenceClassification = Literal[
    "none", "talli_defect", "source_defect", "presentation_only", "unresolved_judgment"
]
ValidationRerunResult = Literal["not_required", "pending", "passed", "failed"]
ValidationPackageOutcome = Literal[
    "not_applicable", "pending", "accepted", "blocked", "failed"
]

VALIDATION_TASKS: Final = (
    "eligibility_precheck",
    "eligibility_definitive",
    "company_year_admission",
    "opening_reconstruction",
    "bank_connection",
    "bank_import",
    "bookkeeping",
    "year_close",
    "shareholder_register_filing",
    "company_tax_filing",
    "annual_accounts_filing",
    "archive_export",
)
VALIDATION_STATES: Final = ("started", "completed", "failed", "blocked")
VALIDATION_STAGES: Final = (
    "eligibility",
    "onboarding",
    "reconstruction",
    "banking",
    "bookkeeping",
    "year_close",
    "shareholder_register",
    "company_tax",
    "annual_accounts",
    "archive",
)
VALIDATION_REASONS: Final = (
    "none",
    "unsupported_boundary",
    "missing_evidence",
    "authorization_required",
    "provider_unavailable",
    "technical_failure",
    "difference_detected",
    "participant_withdrew",
)
VALIDATION_INTERVENTION_TYPES: Final = (
    "none",
    "navigation_help",
    "evidence_help",
    "technical_support",
)
VALIDATION_DIFFERENCE_CLASSIFICATIONS: Final = (
    "none",
    "talli_defect",
    "source_defect",
    "presentation_only",
    "unresolved_judgment",
)
VALIDATION_RERUN_RESULTS: Final = ("not_required", "pending", "passed", "failed")
VALIDATION_PACKAGE_OUTCOMES: Final = (
    "not_applicable",
    "pending",
    "accepted",
    "blocked",
    "failed",
)

_RUN_ID = re.compile(r"^V2P8-[0-9]{8}-[A-Z0-9]{4,16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID_V4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_MAXIMUM_RUNTIME = timedelta(days=90)


@dataclass(frozen=True)
class BoundedValidationObservation:
    """The complete allowlisted evaluation payload; free text has no field."""

    observation_id: UUID
    task: ValidationTask
    state: ValidationState
    stage: ValidationStage
    reason: ValidationReason
    elapsed_milliseconds: int
    intervention_type: ValidationInterventionType
    intervention_count: int
    intervention_milliseconds: int
    difference_classification: ValidationDifferenceClassification
    rerun_result: ValidationRerunResult
    package_outcome: ValidationPackageOutcome

    def __post_init__(self) -> None:
        checks = (
            (self.task in VALIDATION_TASKS, "validation_observation_task_invalid"),
            (self.state in VALIDATION_STATES, "validation_observation_state_invalid"),
            (self.stage in VALIDATION_STAGES, "validation_observation_stage_invalid"),
            (self.reason in VALIDATION_REASONS, "validation_observation_reason_invalid"),
            (
                self.intervention_type in VALIDATION_INTERVENTION_TYPES,
                "validation_observation_intervention_invalid",
            ),
            (
                self.difference_classification
                in VALIDATION_DIFFERENCE_CLASSIFICATIONS,
                "validation_observation_difference_invalid",
            ),
            (
                self.rerun_result in VALIDATION_RERUN_RESULTS,
                "validation_observation_rerun_invalid",
            ),
            (
                self.package_outcome in VALIDATION_PACKAGE_OUTCOMES,
                "validation_observation_package_outcome_invalid",
            ),
            (
                isinstance(self.elapsed_milliseconds, int)
                and not isinstance(self.elapsed_milliseconds, bool)
                and 0 <= self.elapsed_milliseconds <= 86_400_000,
                "validation_observation_elapsed_invalid",
            ),
            (
                isinstance(self.intervention_count, int)
                and not isinstance(self.intervention_count, bool)
                and 0 <= self.intervention_count <= 100,
                "validation_observation_intervention_count_invalid",
            ),
            (
                isinstance(self.intervention_milliseconds, int)
                and not isinstance(self.intervention_milliseconds, bool)
                and 0 <= self.intervention_milliseconds <= 86_400_000,
                "validation_observation_intervention_duration_invalid",
            ),
        )
        for valid, code in checks:
            if not valid:
                raise ValueError(code)


@dataclass(frozen=True)
class AuthorizedValidationObservation:
    """Server-bound command whose authority is revalidated atomically by storage."""

    entitlement_id: UUID
    approved_run_id: str
    release_sha256: str
    participant_information_sha256: str
    subject_binding_sha256: str
    observation: BoundedValidationObservation


class ValidationObservationGateway(Protocol):
    async def record(self, command: AuthorizedValidationObservation) -> bool: ...


class ValidationObservationError(RuntimeError):
    """Stable adapter failure kept inside the passive observer boundary."""

    @classmethod
    def invalid(cls) -> ValidationObservationError:
        return cls("validation_observation_invalid")

    @classmethod
    def unavailable(cls) -> ValidationObservationError:
        return cls("validation_observation_unavailable")


@dataclass(frozen=True)
class ValidationObservationConfiguration:
    mode: ValidationObservationMode
    entitlement_id: UUID | None
    approved_run_id: str | None
    starts_at: datetime | None
    expires_at: datetime | None
    release_sha256: str | None
    participant_information_sha256: str | None
    subject_binding_key: str | None
    blocking_reasons: tuple[str, ...]

    @classmethod
    def from_values(
        cls,
        *,
        requested_mode: object = None,
        product_mode: object = None,
        entitlement_id: object = None,
        approved_run_id: object = None,
        starts_at: object = None,
        expires_at: object = None,
        release_sha256: object = None,
        participant_information_sha256: object = None,
        subject_binding_key: object = None,
        now: datetime | None = None,
    ) -> ValidationObservationConfiguration:
        checked_at = now or datetime.now(UTC)
        reasons: list[str] = []
        parsed_entitlement: UUID | None = None
        parsed_start: datetime | None = None
        parsed_expiry: datetime | None = None

        if requested_mode != "invited-pilot":
            reasons.append("mode:not-invited-pilot")
        if product_mode != "prelaunch-validation":
            reasons.append("product-mode:not-prelaunch-validation")
        try:
            if not isinstance(entitlement_id, str) or not _UUID_V4.fullmatch(
                entitlement_id
            ):
                raise ValueError
            parsed_entitlement = UUID(entitlement_id)
        except (AttributeError, TypeError, ValueError):
            reasons.append("entitlement:invalid")
        if not isinstance(approved_run_id, str) or not _RUN_ID.fullmatch(
            approved_run_id
        ):
            reasons.append("run:invalid")

        try:
            parsed_start = datetime.fromisoformat(str(starts_at))
            if parsed_start.tzinfo is None:
                raise ValueError
            parsed_start = parsed_start.astimezone(UTC)
        except (TypeError, ValueError):
            reasons.append("window:start-invalid")
        try:
            parsed_expiry = datetime.fromisoformat(str(expires_at))
            if parsed_expiry.tzinfo is None:
                raise ValueError
            parsed_expiry = parsed_expiry.astimezone(UTC)
        except (TypeError, ValueError):
            reasons.append("window:expiry-invalid")

        if parsed_start is not None and parsed_start > checked_at:
            reasons.append("window:not-started")
        if parsed_expiry is not None and parsed_expiry <= checked_at:
            reasons.append("window:expired")
        if (
            parsed_start is not None
            and parsed_expiry is not None
            and parsed_expiry <= parsed_start
        ):
            reasons.append("window:invalid")
        if parsed_expiry is not None and parsed_expiry > checked_at + _MAXIMUM_RUNTIME:
            reasons.append("window:too-long")
        if not isinstance(release_sha256, str) or not _SHA256.fullmatch(
            release_sha256
        ):
            reasons.append("release:invalid")
        if not isinstance(
            participant_information_sha256, str
        ) or not _SHA256.fullmatch(participant_information_sha256):
            reasons.append("participant-information:invalid")
        if not isinstance(subject_binding_key, str) or len(subject_binding_key) < 32:
            reasons.append("subject-binding-key:invalid")

        if reasons:
            return cls(
                mode="off",
                entitlement_id=None,
                approved_run_id=None,
                starts_at=None,
                expires_at=None,
                release_sha256=None,
                participant_information_sha256=None,
                subject_binding_key=None,
                blocking_reasons=tuple(reasons),
            )
        return cls(
            mode="invited-pilot",
            entitlement_id=parsed_entitlement,
            approved_run_id=str(approved_run_id),
            starts_at=parsed_start,
            expires_at=parsed_expiry,
            release_sha256=str(release_sha256),
            participant_information_sha256=str(participant_information_sha256),
            subject_binding_key=str(subject_binding_key),
            blocking_reasons=(),
        )


class PassiveValidationObserver:
    """Write after an outcome without returning a value product code can branch on."""

    def __init__(
        self,
        configuration: ValidationObservationConfiguration,
        gateway: ValidationObservationGateway,
        *,
        timeout_seconds: float = 1.0,
    ) -> None:
        self._configuration = configuration
        self._gateway = gateway
        self._timeout_seconds = timeout_seconds

    async def after_outcome(
        self,
        *,
        subject_identifier: str,
        observation: BoundedValidationObservation,
    ) -> None:
        configuration = self._configuration
        if configuration.mode != "invited-pilot":
            return
        try:
            if not subject_identifier:
                raise ValueError("validation_observation_subject_invalid")
            if (
                configuration.entitlement_id is None
                or configuration.approved_run_id is None
                or configuration.release_sha256 is None
                or configuration.participant_information_sha256 is None
                or configuration.subject_binding_key is None
            ):
                raise ValueError("validation_observation_authority_invalid")
            subject_digest = hmac.new(
                configuration.subject_binding_key.encode(),
                subject_identifier.encode(),
                hashlib.sha256,
            ).hexdigest()
            command = AuthorizedValidationObservation(
                entitlement_id=configuration.entitlement_id,
                approved_run_id=configuration.approved_run_id,
                release_sha256=configuration.release_sha256,
                participant_information_sha256=(
                    configuration.participant_information_sha256
                ),
                subject_binding_sha256=subject_digest,
                observation=observation,
            )
            await asyncio.wait_for(
                self._gateway.record(command), timeout=self._timeout_seconds
            )
        except (Exception, asyncio.CancelledError):
            # Observation is acceptance evidence, never product authority. Missing
            # evidence is detected by the completeness gate and must be rerun.
            return


Adapter = TypeVar("Adapter", bound=Callable[..., object])


def validation_observation_adapter(
    port: type[object],
) -> Callable[[Adapter], Adapter]:
    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


__all__ = [
    "AuthorizedValidationObservation",
    "BoundedValidationObservation",
    "PassiveValidationObserver",
    "ValidationObservationConfiguration",
    "ValidationObservationError",
    "ValidationObservationGateway",
    "validation_observation_adapter",
]
