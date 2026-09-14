"""Deterministic no-provider driver for frozen Accounts rehearsal checkpoints."""
import asyncio
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError

ROOT = Path(__file__).resolve().parents[3]
CASES = ['prepare', 'validation_errors', 'connect', 'create_instance', 'upload_main_form',
         'upload_company_accounts', 'validate_instance', 'lock_for_signing', 'get_signing_handoff',
         'resume_pending', 'resume_completed', 'get_submission_evidence', 'completed_replay',
         'partial_upload', 'mismatched_hash', 'save_first', 'save_after_upload']
NOW = '2026-09-14T12:00:00.000Z'
ORG = '310279617'


def trace(module, scenario, *, relocated):
    events, checkpoints = [], []
    main, accounts = '<main/>', '<accounts/>'
    from hashlib import sha256
    prior = {'schemaVersion': 1, 'status': 'locked_for_person_signing', 'environment': 'test',
        'productionEnabled': False, 'companyOrgNumber': ORG, 'incomeYear': 2025,
        'instance': {'id': 'instance', 'dataIds': {'mainForm': 'main', 'companyAccounts': 'accounts'},
            'createdProcessTask': 'data', 'mainFormUploaded': True, 'companyAccountsUploaded': True, 'locked': True},
        'payloadHashes': {'mainForm': sha256(main.encode()).hexdigest(), 'companyAccounts': sha256(accounts.encode()).hexdigest()},
        'validation': {'hasErrors': False, 'issues': []}, 'evidenceFile': 'evidence.json',
        'signed': False, 'submitted': False, 'submission': None, 'signingUrl': 'https://synthetic.test/signing'}
    if scenario == 'completed_replay':
        prior.update(status='submitted_and_archived', signed=True, submitted=True,
            submission={'receipt': {'reference': 'receipt'}, 'archiveReference': 'archive'})
    elif scenario == 'partial_upload':
        prior['status'] = 'failed_retryable'
        prior['instance'].update(companyAccountsUploaded=False, locked=False)
    elif scenario == 'mismatched_hash':
        prior['payloadHashes']['mainForm'] = 'different'
    elif scenario not in ('resume_pending', 'resume_completed', 'get_submission_evidence'):
        prior = None

    def record(name, values=None):
        events.append({'operation': name, 'input': copy.deepcopy(values)})
        if name == scenario:
            raise AnnualAccountsAuthorityError('Synthetic network failure.', code='ANNUAL_ACCOUNTS_NETWORK_ERROR', retryable=True)

    class Client:
        async def create_instance(self, **values):
            record('create_instance', values)
            return {'id': 'instance', 'dataIds': {'mainForm': 'main', 'companyAccounts': 'accounts'}, 'processTask': 'data'}
        async def upload_main_form(self, **values): record('upload_main_form', values)
        async def upload_company_accounts(self, **values): record('upload_company_accounts', values)
        async def validate_instance(self, **values):
            record('validate_instance', values)
            return {'hasErrors': scenario == 'validation_errors', 'issues': [{'code': 'RR0002_TEST', 'severity': 'Error'}] if scenario == 'validation_errors' else []}
        async def lock_for_signing(self, **values):
            record('lock_for_signing', values)
            return {'processTask': 'signing', 'locked': True}
        async def get_signing_handoff(self, **values):
            record('get_signing_handoff', values)
            return {'signingUrl': 'https://synthetic.test/signing', 'signed': False, 'submitted': False}
        async def get_submission_evidence(self, **values):
            record('get_submission_evidence', values)
            completed = scenario == 'resume_completed'
            return {'signed': completed, 'submitted': completed, 'processEndedAt': NOW if completed else None,
                'receipt': {'reference': 'receipt'} if completed else None,
                'archiveReference': 'archive' if completed else None}

    def load(_):
        record('load_evidence')
        return copy.deepcopy(prior)

    def save(_, value):
        record('save_evidence', value)
        if scenario == 'save_first' or scenario == 'save_after_upload' and value['status'] == 'main_form_uploaded':
            raise OSError('Synthetic checkpoint failure.')
        checkpoints.append(copy.deepcopy(value))

    async def connect(_, value):
        record('connect', value)
        assert checkpoints
        return Client()

    def generate(operation, value):
        record('generate', {'operation': operation, 'input': value})
        return {'mainFormXml': main, 'companyAccountsXml': accounts, 'feedback': [{'code': 'Z'}, {'code': 'A'}]}

    def validate(value): record('validate_xml', value)

    seam = __import__('talli_backend.adapters.local_annual_accounts_rehearsal', fromlist=['unused']) if relocated else module
    with TemporaryDirectory() as directory:
        case = json.loads((ROOT / 'tests/fixtures/authority/annual-accounts-simple-holding-2025.json').read_text())
        case_path = Path(directory) / 'case.json'
        case_path.write_text(json.dumps(case))
        environment = {'TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE': 'true', 'TALLI_MASKINPORTEN_ENVIRONMENT': 'test',
            'TALLI_MASKINPORTEN_SCOPE': 'altinn:instances.read altinn:instances.write',
            'TALLI_ANNUAL_ACCOUNTS_CASE_PATH': str(case_path),
            'TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH': str(Path(directory) / 'evidence.json'),
            'TALLI_MASKINPORTEN_SYSTEM_USER_ORG': ORG, 'TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF': 'synthetic-ref',
            'TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL': 'synthetic@example.test',
            'TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE': '2026-06-30',
            'TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE': 'Synthetic Person'}
        with patch.object(seam, 'read_evidence', load), patch.object(seam, 'write_evidence', save), \
             patch.object(seam, 'now', lambda: NOW), patch.object(seam, 'git_commit', lambda: 'synthetic-revision'):
            try:
                output = {'value': asyncio.run(module.run(environment, client_factory=connect, generate=generate, validate=validate))}
            except Exception as error:
                output = {'error': {'type': type(error).__name__, 'message': str(error)}}
    return {'events': events, 'checkpoints': checkpoints, 'output': output}
