"""Released TT02 evidence projection, preserving ordered validation failures."""
from collections.abc import Mapping
from hashlib import sha256
import re

from .date_parse import finite_date_parse
from .numbers import SPACE
from .public import AnnualAccountsEvidenceInput, AnnualAccountsEvidenceProjection

_UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def _object(value):
    return value if isinstance(value, Mapping) else {}


def _string(value, label):
    if not isinstance(value, str) or not value.strip(SPACE):
        raise ValueError(f'{label} mangler i TT02-evidensen.')
    return value.strip(SPACE)


def _required(value, label):
    if not value.strip(SPACE):
        raise ValueError(f'{label} mangler.')
    return value.strip(SPACE)


def project(input: AnnualAccountsEvidenceInput) -> AnnualAccountsEvidenceProjection:
    evidence = _object(input.evidence)
    organization = _required(input.expected_organization_number, 'Forventet organisasjonsnummer')
    if not re.fullmatch(r'[0-9]{9}', organization) or _string(evidence.get('companyOrgNumber'), 'Organisasjonsnummer') != organization:
        raise ValueError('TT02-evidensens organisasjonsnummer matcher ikke selskapet.')
    if evidence.get('environment') != 'test':
        raise ValueError('Bare TT02 test-evidens kan importeres.')
    if evidence.get('productionEnabled') is not False:
        raise ValueError('TT02-evidens med produksjon aktivert kan ikke importeres.')
    if evidence.get('systemUserResource') != 'app_brg_aarsregnskap-vanlig-202406':
        raise ValueError('TT02-evidensen bruker feil årsregnskapsressurs.')
    if evidence.get('status') != 'submitted_and_archived' or evidence.get('signed') is not True or evidence.get('submitted') is not True:
        raise ValueError('TT02-evidensen må være signert og sendt før import.')
    if _object(evidence.get('validation')).get('hasErrors') is not False:
        raise ValueError('TT02-evidensen har valideringsfeil.')
    instance_id = _string(_object(evidence.get('instance')).get('id'), 'Instans-id')
    if not re.fullmatch(r'[0-9]+/' + _UUID, instance_id, re.IGNORECASE | re.ASCII):
        raise ValueError('TT02-evidensens instans-id er ugyldig.')
    submission = _object(evidence.get('submission'))
    if any(submission.get(key) is not True for key in ('processCompleted', 'signed', 'submitted', 'archived')) or not finite_date_parse(_string(submission.get('processEndedAt'), 'Prosesslutt')):
        raise ValueError('TT02-evidensens signerings- og innsendingstilstand er ufullstendig.')
    expected_archive = f'https://platform.tt02.altinn.no/storage/api/v1/instances/{instance_id}'
    archive = _string(submission.get('archiveReference'), 'Arkivreferanse')
    if archive != expected_archive:
        raise ValueError('TT02-evidensens arkivreferanse er ugyldig.')
    receipt = _object(submission.get('receipt'))
    receipt_id = _string(receipt.get('dataId'), 'Kvitteringsdata-id')
    if not re.fullmatch(_UUID, receipt_id, re.IGNORECASE | re.ASCII) or receipt.get('dataType') != 'ref-data-as-pdf' or receipt.get('contentType') != 'application/pdf':
        raise ValueError('TT02-evidensens kvittering er ugyldig.')
    receipt_reference = _string(receipt.get('reference'), 'Kvitteringsreferanse')
    if receipt_reference != f'{expected_archive}/data/{receipt_id}':
        raise ValueError('TT02-evidensens kvitteringsreferanse er ugyldig.')
    hashes = _object(evidence.get('payloadHashes'))
    main_hash = _string(hashes.get('mainForm'), 'Hovedskjemahash')
    accounts_hash = _string(hashes.get('companyAccounts'), 'Selskapsregnskapshash')
    if not re.fullmatch('[0-9a-f]{64}', main_hash) or not re.fullmatch('[0-9a-f]{64}', accounts_hash):
        raise ValueError('TT02-evidensens payload-hasher er ugyldige.')
    combined_hash = sha256(f'mainForm:{main_hash}\ncompanyAccounts:{accounts_hash}'.encode()).hexdigest()
    inbox = _object(evidence.get('inbox'))
    status = _string(inbox.get('status'), 'Innboksstatus')
    display = _string(inbox.get('displayStatus'), 'Innboksstatusvisning')
    confirmation = _string(inbox.get('confirmation'), 'Innboksbekreftelse')
    return AnnualAccountsEvidenceProjection(
        company_id=_required(input.company_id, 'Company id'), obligation='aarsregnskap',
        environment='test', status='pending', test_reference=f'tt02:{instance_id}',
        feedback_summary=f'{display} ({status}): {confirmation}'.strip(SPACE),
        receipt_reference=receipt_reference, archive_reference=archive,
        evidence_url=input.evidence_url.strip(SPACE) or None if input.evidence_url is not None else None,
        payload_hash=f'sha256:{combined_hash}', recorded_by=_required(input.recorded_by, 'Recorded by'),
        recorded_at=input.recorded_at,
    )
