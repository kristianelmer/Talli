"""Restricted PostgreSQL writer for invited validation observations."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from talli_backend.modules.validation_observation.public import (
    AuthorizedValidationObservation,
    ValidationObservationError,
    ValidationObservationGateway,
    validation_observation_adapter,
)


@dataclass(frozen=True)
class ValidationObservationDatabaseConfiguration:
    database_url: str


@validation_observation_adapter(ValidationObservationGateway)
class SupabaseValidationObservationAdapter(ValidationObservationGateway):
    """Call one typed security-definer function through a SET-only role."""

    def __init__(
        self, configuration: ValidationObservationDatabaseConfiguration
    ) -> None:
        self._configuration = configuration

    @classmethod
    def from_environment(cls) -> SupabaseValidationObservationAdapter:
        return cls(
            ValidationObservationDatabaseConfiguration(
                database_url=os.environ.get(
                    "TALLI_VALIDATION_OBSERVATION_DATABASE_URL", ""
                )
            )
        )

    async def record(self, command: AuthorizedValidationObservation) -> bool:
        if not self._configuration.database_url:
            raise ValidationObservationError.unavailable()

        def execute() -> bool:
            try:
                with psycopg.connect(
                    self._configuration.database_url,
                    connect_timeout=5,
                    row_factory=dict_row,
                ) as connection, connection.transaction():
                    connection.execute(
                        "set local role validation_observation_writer_executor"
                    )
                    observation = command.observation
                    row = connection.execute(
                        """
                        select backend_system.record_validation_observation_v1(
                          %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s
                        ) as inserted
                        """,
                        (
                            observation.observation_id,
                            command.entitlement_id,
                            command.approved_run_id,
                            command.release_sha256,
                            command.participant_information_sha256,
                            command.subject_binding_sha256,
                            observation.task,
                            observation.state,
                            observation.stage,
                            observation.reason,
                            observation.elapsed_milliseconds,
                            observation.intervention_type,
                            observation.intervention_count,
                            observation.intervention_milliseconds,
                            observation.difference_classification,
                            observation.rerun_result,
                            observation.package_outcome,
                        ),
                    ).fetchone()
                    if row is None or not isinstance(row.get("inserted"), bool):
                        raise ValidationObservationError.unavailable()
                    return bool(row["inserted"])
            except ValidationObservationError:
                raise
            except psycopg.OperationalError:
                raise ValidationObservationError.unavailable() from None
            except psycopg.DatabaseError as error:
                if "validation_observation_" in str(error):
                    raise ValidationObservationError.invalid() from None
                raise ValidationObservationError.unavailable() from None

        return await asyncio.to_thread(execute)


__all__ = [
    "SupabaseValidationObservationAdapter",
    "ValidationObservationDatabaseConfiguration",
]
