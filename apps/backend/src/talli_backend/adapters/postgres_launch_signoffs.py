"""Technical signoff persistence with a verified actor and fixed restricted RPCs."""
from asyncio import timeout
from collections.abc import Mapping
import os

import psycopg
from psycopg.rows import dict_row

from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, SupabaseLedgerAdapter, _VerifiedActor
from talli_backend.application.ledger_workflow import LedgerAuthenticationError
from talli_backend.application.launch_signoffs import (
    LaunchSignoffAuthenticationError, LaunchSignoffError, LaunchSignoffKey, LaunchSignoffRecord,
    LaunchSignoffStatus, RecordLaunchSignoff,
)
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.shared.kernel import ErrorCategory, Timestamp, UserId


def _unavailable():
    return LaunchSignoffError('launch_signoff_unavailable', ErrorCategory.DEPENDENCY_UNAVAILABLE)


def _record(row):
    return LaunchSignoffRecord(LaunchSignoffKey(row['key']), LaunchSignoffStatus(row['status']),
        row['reviewer'], Timestamp(row['reviewed_at']), row['evidence_link'], row['decision'],
        UserId(str(row['recorded_by'])), Timestamp(row['updated_at']))


class PostgresLaunchSignoffsAdapter:
    def __init__(self, configuration: LedgerSupabaseConfiguration):
        self._configuration = configuration
        self._authentication = SupabaseLedgerAdapter(configuration)

    @classmethod
    def from_environment(cls):
        return cls(LedgerSupabaseConfiguration(
            url=os.environ.get('SUPABASE_URL',''), anon_key=os.environ.get('SUPABASE_ANON_KEY',''),
            database_url=os.environ.get('TALLI_LEDGER_DATABASE_URL',''),
        ))

    async def session(self, access_token):
        try: session = await self._authentication.session(access_token)
        except LedgerAuthenticationError: raise LaunchSignoffAuthenticationError() from None
        except LedgerError: raise _unavailable() from None
        return PostgresLaunchSignoffSession(self._configuration.database_url, session._verified)


class PostgresLaunchSignoffSession:
    def __init__(self, database_url: str, verified: _VerifiedActor):
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self): return self._verified.actor_id

    async def _transaction(self, work):
        if not self._database_url: raise _unavailable()
        try:
            async with timeout(10), await psycopg.AsyncConnection.connect(
                self._database_url, connect_timeout=5, row_factory=dict_row,
                options='-c statement_timeout=5000 -c lock_timeout=1000',
            ) as connection, connection.transaction():
                await connection.execute('set local role launch_signoff_executor')
                await connection.execute(
                    "select pg_catalog.set_config('talli.verified_actor_id',%s,true), "
                    "pg_catalog.set_config('talli.verified_actor_claims',%s,true)",
                    (str(self.actor_id.subject),self._verified.claims_json),
                )
                return await work(connection)
        except LaunchSignoffError: raise
        except psycopg.DatabaseError as error:
            if 'launch_signoff_operator_required' in str(error):
                raise LaunchSignoffError('launch_signoff_operator_required',ErrorCategory.FORBIDDEN) from None
            if 'launch_signoff_invalid' in str(error) or isinstance(error,psycopg.errors.CheckViolation):
                raise LaunchSignoffError('launch_signoff_invalid',ErrorCategory.INVALID_INPUT) from None
            raise _unavailable() from None
        except (TimeoutError,ValueError,TypeError,KeyError): raise _unavailable() from None

    async def authorize_operator(self, *, admin):
        async def run(connection):
            await connection.execute('select backend_system.assert_launch_signoff_operator_v1(%s::boolean)',(admin,))
        return await self._transaction(run)

    async def list_signoffs(self):
        async def run(connection):
            cursor = await connection.execute('select * from backend_system.list_launch_signoffs_v1()')
            return tuple(_record(row) for row in await cursor.fetchall())
        return await self._transaction(run)

    async def record_signoff(self, command: RecordLaunchSignoff):
        async def run(connection):
            cursor = await connection.execute(
                'select * from backend_system.record_launch_signoff_v1(%s::text,%s::text,%s::text,%s::timestamptz,%s::text,%s::text)',
                (command.key.value,command.status.value,command.reviewer,command.reviewed_at,command.evidence_link,command.decision),
            )
            row = await cursor.fetchone()
            if not row: raise _unavailable()
            return _record(row)
        return await self._transaction(run)
