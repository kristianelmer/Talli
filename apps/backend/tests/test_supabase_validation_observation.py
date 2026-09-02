import asyncio
import os
from uuid import UUID

import pytest

from talli_backend.adapters.supabase_validation_observation import (
    SupabaseValidationObservationAdapter,
    ValidationObservationDatabaseConfiguration,
)
from talli_backend.modules.validation_observation.public import (
    AuthorizedValidationObservation,
    BoundedValidationObservation,
)


DATABASE_URL = os.environ.get("TALLI_VALIDATION_OBSERVATION_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="the real adapter rehearsal is owned by the PostgreSQL runtime test",
)
def test_restricted_adapter_executes_the_real_observation_contract() -> None:
    assert DATABASE_URL is not None
    adapter = SupabaseValidationObservationAdapter(
        ValidationObservationDatabaseConfiguration(database_url=DATABASE_URL)
    )
    command = AuthorizedValidationObservation(
        entitlement_id=UUID("10000000-0000-4000-8000-000000000001"),
        approved_run_id="V2P8-20260829-LOCAL",
        release_sha256="a" * 64,
        participant_information_sha256="b" * 64,
        subject_binding_sha256="c" * 64,
        observation=BoundedValidationObservation(
            observation_id=UUID("30000000-0000-4000-8000-000000000004"),
            task="eligibility_definitive",
            state="completed",
            stage="eligibility",
            reason="none",
            elapsed_milliseconds=500,
            intervention_type="none",
            intervention_count=0,
            intervention_milliseconds=0,
            difference_classification="none",
            rerun_result="not_required",
            package_outcome="not_applicable",
        ),
    )

    assert asyncio.run(adapter.record(command)) is True
    assert asyncio.run(adapter.record(command)) is False
