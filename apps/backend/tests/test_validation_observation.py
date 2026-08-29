import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from talli_backend.modules.validation_observation.public import (
    BoundedValidationObservation,
    PassiveValidationObserver,
    ValidationObservationConfiguration,
)


NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
ENTITLEMENT_ID = UUID("10000000-0000-4000-8000-000000000001")
OBSERVATION_ID = UUID("20000000-0000-4000-8000-000000000002")
SHA_A = "a" * 64
SHA_B = "b" * 64


class ObservationGatewayStub:
    def __init__(self, *, failure: Exception | None = None, delay: float = 0) -> None:
        self.failure = failure
        self.delay = delay
        self.commands = []

    async def record(self, command: object) -> bool:
        self.commands.append(command)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure is not None:
            raise self.failure
        return True


def observation() -> BoundedValidationObservation:
    return BoundedValidationObservation(
        observation_id=OBSERVATION_ID,
        task="company_year_admission",
        state="completed",
        stage="onboarding",
        reason="none",
        elapsed_milliseconds=1200,
        intervention_type="none",
        intervention_count=0,
        intervention_milliseconds=0,
        difference_classification="none",
        rerun_result="not_required",
        package_outcome="not_applicable",
    )


def enabled_configuration() -> ValidationObservationConfiguration:
    return ValidationObservationConfiguration.from_values(
        requested_mode="invited-pilot",
        product_mode="prelaunch-validation",
        entitlement_id=str(ENTITLEMENT_ID),
        approved_run_id="V2P8-20260829-LOCAL",
        starts_at=(NOW - timedelta(minutes=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        release_sha256=SHA_A,
        participant_information_sha256=SHA_B,
        subject_binding_key="local-test-key-with-at-least-32-bytes",
        now=NOW,
    )


def test_bounded_observation_rejects_unknown_or_unbounded_values() -> None:
    with pytest.raises(ValueError, match="validation_observation_task_invalid"):
        BoundedValidationObservation(
            **{**observation().__dict__, "task": "free text is forbidden"}
        )

    with pytest.raises(ValueError, match="validation_observation_elapsed_invalid"):
        BoundedValidationObservation(
            **{**observation().__dict__, "elapsed_milliseconds": 86_400_001}
        )


@pytest.mark.parametrize(
    ("override", "expected_reason"),
    [
        ({"requested_mode": "typo"}, "mode:not-invited-pilot"),
        ({"product_mode": None}, "product-mode:not-prelaunch-validation"),
        ({"product_mode": "launch"}, "product-mode:not-prelaunch-validation"),
        ({"starts_at": (NOW + timedelta(seconds=1)).isoformat()}, "window:not-started"),
        ({"expires_at": NOW.isoformat()}, "window:expired"),
        ({"expires_at": (NOW + timedelta(days=91)).isoformat()}, "window:too-long"),
        ({"approved_run_id": "run-from-browser"}, "run:invalid"),
        ({"entitlement_id": "not-a-uuid"}, "entitlement:invalid"),
        ({"entitlement_id": "10000000-0000-1000-8000-000000000001"}, "entitlement:invalid"),
        ({"release_sha256": "short"}, "release:invalid"),
        ({"participant_information_sha256": "short"}, "participant-information:invalid"),
        ({"subject_binding_key": "short"}, "subject-binding-key:invalid"),
    ],
)
def test_runtime_configuration_fails_closed(
    override: dict[str, object], expected_reason: str
) -> None:
    values: dict[str, object] = {
        "requested_mode": "invited-pilot",
        "product_mode": "prelaunch-validation",
        "entitlement_id": str(ENTITLEMENT_ID),
        "approved_run_id": "V2P8-20260829-LOCAL",
        "starts_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "release_sha256": SHA_A,
        "participant_information_sha256": SHA_B,
        "subject_binding_key": "local-test-key-with-at-least-32-bytes",
        "now": NOW,
    }
    values.update(override)

    configuration = ValidationObservationConfiguration.from_values(**values)

    assert configuration.mode == "off"
    assert expected_reason in configuration.blocking_reasons


def test_off_mode_does_not_touch_the_observation_gateway() -> None:
    gateway = ObservationGatewayStub()
    configuration = ValidationObservationConfiguration.from_values(
        requested_mode="off",
        product_mode="prelaunch-validation",
        now=NOW,
    )
    observer = PassiveValidationObserver(configuration, gateway)

    assert asyncio.run(
        observer.after_outcome(subject_identifier="company-id", observation=observation())
    ) is None
    assert gateway.commands == []


def test_invited_mode_sends_only_server_authority_and_bounded_codes() -> None:
    gateway = ObservationGatewayStub()
    observer = PassiveValidationObserver(enabled_configuration(), gateway)

    assert asyncio.run(
        observer.after_outcome(subject_identifier="company-id", observation=observation())
    ) is None

    assert len(gateway.commands) == 1
    command = gateway.commands[0]
    assert command.entitlement_id == ENTITLEMENT_ID
    assert command.approved_run_id == "V2P8-20260829-LOCAL"
    assert command.release_sha256 == SHA_A
    assert command.participant_information_sha256 == SHA_B
    assert command.subject_binding_sha256 != "company-id"
    assert len(command.subject_binding_sha256) == 64
    assert command.observation == observation()


@pytest.mark.parametrize(
    "gateway",
    [
        ObservationGatewayStub(failure=RuntimeError("database unavailable")),
        ObservationGatewayStub(delay=0.05),
    ],
)
def test_writer_failure_or_timeout_is_swallowed(gateway: ObservationGatewayStub) -> None:
    observer = PassiveValidationObserver(
        enabled_configuration(), gateway, timeout_seconds=0.001
    )
    settled_product_result = object()

    async def settled_action() -> object:
        result = settled_product_result
        await observer.after_outcome(
            subject_identifier="company-id", observation=observation()
        )
        return result

    assert asyncio.run(settled_action()) is settled_product_result
    assert len(gateway.commands) == 1
