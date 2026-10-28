"""Fail-closed restored backend barrier, independent of cached dependency health.

Auth and Storage listeners must stay internal at construction; this middleware
cannot protect an independently published Supabase gateway. Restore orchestration
must check the same gate before opening any of those listeners.
"""
import asyncio
from pathlib import Path
from typing import Mapping
from uuid import UUID

from talli_backend.adapters.deletion_journal import JournalHead, LocalDeletionJournal, replay_is_current

PREFIX = 'TALLI_RESTORE_'


def configured_restore_gate(environment: Mapping[str, str]):
    settings = {k: v for k, v in environment.items() if k.startswith(PREFIX)}
    if not settings:
        return None
    try:
        target = str(UUID(settings[PREFIX+'TARGET_ID']))
        journal = LocalDeletionJournal(Path(settings[PREFIX+'JOURNAL_PATH']),
            customer_root=Path(settings[PREFIX+'CUSTOMER_ROOT']), stream=settings[PREFIX+'JOURNAL_STREAM'])
        receipt = Path(settings[PREFIX+'REPLAY_RECEIPT'])
        minimum = JournalHead(journal.stream, int(settings[PREFIX+'MIN_SEQUENCE']), settings[PREFIX+'MIN_SHA256'])
        if (minimum.sequence < 0 or len(minimum.sha256) != 64
                or any(c not in '0123456789abcdef' for c in minimum.sha256)):
            raise ValueError('invalid restore head')
    except Exception:
        async def closed(): return False
        return closed

    async def check():
        try:
            async with asyncio.timeout(1):
                return await asyncio.to_thread(replay_is_current, journal, receipt=receipt, target=target, minimum=minimum)
        except Exception:
            return False
    return check


class RestoreQuarantineMiddleware:
    def __init__(self, app, gate, problem_response):
        self.app, self.gate, self.problem_response = app, gate, problem_response

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/health/live' or self.gate is None:
            return await self.app(scope, receive, send)
        if await self.gate():
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse
        if scope['path'] == '/health/ready':
            response = JSONResponse({'status': 'not_ready'}, status_code=503)
        else:
            from starlette.requests import Request
            response = self.problem_response(Request(scope), status=503, code='RESTORE_QUARANTINED',
                title='Restored target is quarantined', detail='Deletion-journal replay is not verified for this restored target.')
        response.headers['Cache-Control'] = 'no-store'
        await response(scope, receive, send)
