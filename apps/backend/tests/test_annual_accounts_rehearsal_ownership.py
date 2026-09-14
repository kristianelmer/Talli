"""One local journal has one writer, including concurrent tasks and processes."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from talli_backend.adapters import local_annual_accounts_rehearsal as local
from talli_backend.authority_tools.annual_accounts_test import run
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError


def environment(tmp_path):
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'synthetic': True, 'environment': 'test',
        'company': {'orgNumber': '310279617', 'incomeYear': 2025}, 'ledgerEntries': []}))
    return {'TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE': 'true',
        'TALLI_MASKINPORTEN_ENVIRONMENT': 'test',
        'TALLI_MASKINPORTEN_SCOPE': 'altinn:instances.read altinn:instances.write',
        'TALLI_MASKINPORTEN_SYSTEM_USER_ORG': '310279617',
        'TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF': 'synthetic',
        'TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL': 'x@example.invalid',
        'TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE': '2026-06-30',
        'TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE': 'Synthetic Person',
        'TALLI_ANNUAL_ACCOUNTS_CASE_PATH': str(case),
        'TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH': str(tmp_path / 'evidence.json')}


def generated(*_):
    return {'mainFormXml': '<main/>', 'companyAccountsXml': '<accounts/>', 'feedback': []}


class Provider:
    def __init__(self): self.creates = self.locks = 0
    async def create_instance(self, **_):
        self.creates += 1
        return {'id': f'instance-{self.creates}', 'dataIds': {'mainForm': 'main', 'companyAccounts': 'accounts'}, 'processTask': 'data'}
    async def upload_main_form(self, **_): pass
    async def upload_company_accounts(self, **_): pass
    async def validate_instance(self, **_): return {'hasErrors': False, 'issues': []}
    async def lock_for_signing(self, **_):
        self.locks += 1
        return {'processTask': 'signing'}
    async def get_signing_handoff(self, **_): return {'signingUrl': 'https://synthetic.invalid/signing'}
    async def get_submission_evidence(self, **_):
        return {'signed': False, 'submitted': False, 'processEndedAt': None}


@pytest.mark.parametrize('alias', [False, True])
def test_concurrent_cli_rejects_before_credentials_and_preserves_one_instance(tmp_path, alias):
    env = environment(tmp_path)
    second_env = dict(env)
    if alias:
        linked = tmp_path / 'alias'
        linked.symlink_to(tmp_path, target_is_directory=True)
        second_env['TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH'] = str(linked / 'evidence.json')
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        provider, connects = Provider(), []
        async def connect(*_):
            connects.append(True)
            entered.set()
            await release.wait()
            return provider
        kwargs = dict(client_factory=connect, generate=generated, validate=lambda *_: None)
        first = asyncio.create_task(run(env, **kwargs))
        await entered.wait()
        try:
            with pytest.raises(AnnualAccountsAuthorityError) as rejected:
                await asyncio.wait_for(run(second_env, **kwargs), timeout=1)
            assert rejected.value.code == 'ANNUAL_ACCOUNTS_REHEARSAL_IN_PROGRESS'
            assert not rejected.value.retryable
            assert len(connects) == 1
        finally:
            release.set()
            result = await first
        assert provider.creates == provider.locks == 1
        assert json.loads(Path(env['TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH']).read_text())['instance']['id'] == result['instanceId']
        # Ownership is released after success; the next run only reads status.
        await run(env, **kwargs)
        assert provider.creates == provider.locks == 1
    with patch.object(local, 'git_commit', lambda: 'synthetic-revision'):
        asyncio.run(scenario())


@pytest.mark.parametrize('failure', [ValueError, OSError, KeyboardInterrupt, asyncio.CancelledError])
def test_exclusive_ownership_released_on_every_exit(tmp_path, failure):
    env = environment(tmp_path)
    io = local.LocalAnnualAccountsRehearsal(env, client_factory=None, generate=generated, validate=None)
    with pytest.raises(failure):
        with io.exclusive_evidence():
            raise failure()
    with io.exclusive_evidence():
        io.load_case()
        io.save_evidence({'status': 'prepared'})
    assert json.loads(Path(env['TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH']).read_text()) == {'status': 'prepared'}


def test_process_lock_survives_atomic_replacement_and_releases_after_process_death(tmp_path):
    env = environment(tmp_path)
    io = local.LocalAnnualAccountsRehearsal(env, client_factory=None, generate=generated, validate=None)
    program = '''import json,sys,time
from talli_backend.adapters.local_annual_accounts_rehearsal import LocalAnnualAccountsRehearsal
io=LocalAnnualAccountsRehearsal(json.loads(sys.stdin.readline()),client_factory=None,generate=None,validate=None)
with io.exclusive_evidence():
 io.load_case()
 io.save_evidence({'pendingAuthorityOperation': {'operation': 'create_instance'}})
 print('owned',flush=True)
 time.sleep(60)
'''
    child = subprocess.Popen([sys.executable, '-c', program], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
    try:
        child.stdin.write(json.dumps(env) + '\n'); child.stdin.flush()
        assert child.stdout.readline().strip() == 'owned'
        with pytest.raises(AnnualAccountsAuthorityError) as rejected:
            with io.exclusive_evidence(): pass
        assert rejected.value.code == 'ANNUAL_ACCOUNTS_REHEARSAL_IN_PROGRESS'
    finally:
        child.terminate(); child.wait(timeout=5)
        child.stdin.close(); child.stdout.close(); child.stderr.close()
    with io.exclusive_evidence():
        io.load_case()
        assert io.load_evidence()['pendingAuthorityOperation']['operation'] == 'create_instance'
