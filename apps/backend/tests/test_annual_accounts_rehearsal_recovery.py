"""Ambiguous create/lock attempts cannot be repeated from persisted evidence."""
import asyncio
import copy

import pytest

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsAuthorityError, AnnualAccountsRehearsalConfiguration, rehearse_annual_accounts,
)

CONFIG = AnnualAccountsRehearsalConfiguration(approved_test_write='true', authority_environment='test',
    scope='altinn:instances.read altinn:instances.write', system_user_org='310279617', external_reference='synthetic',
    contact_email='x@example.invalid', approval_date='2026-06-30', confirming_representative='Synthetic Person')


class EvidenceIO:
    def __init__(self, operation, failure):
        self.operation, self.failure = operation, failure
        self.saved, self.calls, self.at_effect = None, [], []
        self.failed = False

    def load_case(self):
        return {'synthetic': True, 'environment': 'test', 'company': {'orgNumber': '310279617', 'incomeYear': 2025}, 'ledgerEntries': []}

    def load_evidence(self): return copy.deepcopy(self.saved)
    def evidence_filename(self): return 'in-memory-evidence.json'
    def case_filename(self): return 'synthetic.json'
    def revision(self): return 'synthetic-revision'
    def timestamp(self): return '2026-09-14T12:00:00.000Z'
    def generate(self, *_): return {'mainFormXml': '<main/>', 'companyAccountsXml': '<accounts/>', 'feedback': []}
    def validate_documents(self, *_): pass

    def save_evidence(self, evidence):
        completed = evidence.get('status') == ('instance_created' if self.operation == 'create_instance' else 'locked')
        if completed and self.failure == 'checkpoint_write' and not self.failed:
            self.failed = True
            raise OSError('Synthetic checkpoint failure after provider success')
        self.saved = copy.deepcopy(evidence)

    async def connect(self, *_):
        self.calls.append('connect')
        return self

    async def effect(self, name):
        self.calls.append(name)
        self.at_effect.append((name, copy.deepcopy(self.saved)))
        if name == self.operation and not self.failed and self.failure != 'checkpoint_write':
            self.failed = True
            if self.failure == 'lost_response':
                raise AnnualAccountsAuthorityError('Response lost after effect.', code='ANNUAL_ACCOUNTS_NETWORK_ERROR', retryable=True)
            if self.failure == 'interruption':
                raise KeyboardInterrupt('Synthetic interruption after effect')
            if self.failure == 'malformed_response': return True
        return False

    async def create_instance(self, **_):
        if await self.effect('create_instance'): return {}
        return {'id': 'created-instance', 'dataIds': {'mainForm': 'main', 'companyAccounts': 'accounts'}, 'processTask': 'data'}

    async def upload_main_form(self, **_): self.calls.append('upload_main_form')
    async def upload_company_accounts(self, **_): self.calls.append('upload_company_accounts')
    async def validate_instance(self, **_): return {'hasErrors': False, 'issues': []}

    async def lock_for_signing(self, **_):
        if await self.effect('lock_for_signing'): return {}
        return {'processTask': 'signing'}

    async def get_signing_handoff(self, **_): return {'signingUrl': 'https://synthetic.invalid/signing'}


@pytest.mark.parametrize('operation', ['create_instance', 'lock_for_signing'])
@pytest.mark.parametrize('failure', ['lost_response', 'malformed_response', 'checkpoint_write', 'interruption'])
def test_ambiguous_effect_remains_durable_and_rerun_cannot_connect(operation, failure):
    io = EvidenceIO(operation, failure)
    with pytest.raises((AnnualAccountsAuthorityError, KeyError, OSError, KeyboardInterrupt)):
        asyncio.run(rehearse_annual_accounts(CONFIG, io))
    assert io.saved['pendingAuthorityOperation']['operation'] == operation
    assert next(state for name, state in io.at_effect if name == operation)['pendingAuthorityOperation']['operation'] == operation
    before = list(io.calls)
    with pytest.raises(AnnualAccountsAuthorityError) as rejected:
        asyncio.run(rehearse_annual_accounts(CONFIG, io))
    assert rejected.value.code == 'ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
    assert not rejected.value.retryable
    assert io.calls == before
    assert io.calls.count(operation) == 1


@pytest.mark.parametrize('operation', ['create_instance', 'lock_for_signing'])
def test_legacy_ambiguous_checkpoint_cannot_repeat_effect(operation):
    io = EvidenceIO(operation, 'lost_response')
    with pytest.raises(AnnualAccountsAuthorityError): asyncio.run(rehearse_annual_accounts(CONFIG, io))
    io.saved.pop('pendingAuthorityOperation', None)
    io.saved.pop('operationJournalVersion', None)
    io.saved['status'] = 'failed_retryable'
    before = list(io.calls)
    with pytest.raises(AnnualAccountsAuthorityError) as rejected: asyncio.run(rehearse_annual_accounts(CONFIG, io))
    assert rejected.value.code == 'ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
    assert io.calls == before


def test_confirmed_lock_with_lost_handoff_resumes_by_reading_submission_only():
    class HandoffIO(EvidenceIO):
        async def get_signing_handoff(self, **_):
            raise AnnualAccountsAuthorityError('Synthetic handoff read failure', code='ANNUAL_ACCOUNTS_NETWORK_ERROR', retryable=True)

        async def get_submission_evidence(self, **_):
            self.calls.append('get_submission_evidence')
            return {'signed': True, 'submitted': True, 'processEndedAt': self.timestamp(),
                'receipt': {'reference': 'receipt'}, 'archiveReference': 'archive'}

    io = HandoffIO('never', 'none')
    with pytest.raises(AnnualAccountsAuthorityError): asyncio.run(rehearse_annual_accounts(CONFIG, io))
    assert io.saved['instance']['locked'] is True
    assert 'pendingAuthorityOperation' not in io.saved
    before = len(io.calls)
    result = asyncio.run(rehearse_annual_accounts(CONFIG, io))
    assert io.calls[before:] == ['connect', 'get_submission_evidence']
    assert result['status'] == 'submitted_and_archived'
    assert result['receiptReference'] == 'receipt'
