"""Strict, deterministic sanitized TT02 receipt projection owned by Company Tax."""
from __future__ import annotations

import calendar
import hashlib
import re
from collections.abc import Mapping

from ada_url import URL

_SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
_UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
_SCOPES = ('altinn:instances.read', 'altinn:instances.write', 'skatteetaten:formueinntekt/skattemelding')
_SCHEMAS = ('naeringsspesifikasjon_v6_ekstern.xsd', 'skattemeldingUpersonlig_v5_ekstern.xsd', 'skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd')


def _object(value):
    return value if isinstance(value, Mapping) else {}


def _string(value, label):
    if not isinstance(value, str) or not value.strip(_SPACE):
        raise ValueError(f'{label} mangler i TT02-evidensen.')
    return value.strip(_SPACE)


def _required(value, label):
    if not isinstance(value, str) or not value.strip(_SPACE):
        raise ValueError(f'{label} mangler.')
    return value.strip(_SPACE)


def _instant(value, label):
    value = _string(value, label)
    match = re.fullmatch(r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?(Z|[+-][0-9]{2}:[0-9]{2})', value)
    if match:
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        zone = match[8]
        offset_hour, offset_minute = (0, 0) if zone == 'Z' else (int(zone[1:3]), int(zone[4:6]))
        if 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1] and hour <= 23 and minute <= 59 and second <= 59 and offset_hour <= 23 and offset_minute <= 59:
            return value
    raise ValueError(f'{label} er ugyldig i TT02-evidensen.')


def _instant_order(value):
    year, month, day = int(value[:4]), int(value[5:7]), int(value[8:10])
    prior = year - 1
    days = 365 * prior + prior // 4 - prior // 100 + prior // 400
    days += sum(calendar.monthrange(year, m)[1] for m in range(1, month)) + day - 1
    seconds = days * 86400 + int(value[11:13]) * 3600 + int(value[14:16]) * 60 + int(value[17:19])
    match = re.search(r'(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})$', value)
    zone = match[2]
    if zone != 'Z':
        seconds -= (1 if zone[0] == '+' else -1) * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
    return seconds, (match[1] or '').ljust(6, '0')


def _safe_url(value):
    raw = value or ''
    normalized = raw.strip(_SPACE)
    if not normalized:
        return None
    if raw != normalized or re.search(r'[\x00-\x20\x7f]', normalized) or len(normalized.encode('utf-16-le', 'surrogatepass')) // 2 > 2048 or '?' in normalized or '#' in normalized or re.search(r'(?:^|/)\.{1,2}(?:/|$)|%(?:2e|2f|5c)|current_document_reference_sentinel', normalized, re.I):
        raise ValueError('TT02-evidenslenken må være en avgrenset HTTPS-lenke uten query eller fragment.')
    try:
        parsed = URL(normalized)
    except ValueError:
        raise ValueError('TT02-evidenslenken må være en absolutt HTTPS-lenke.') from None
    if parsed.protocol != 'https:' or not parsed.hostname or parsed.username or parsed.password or parsed.port or parsed.search or parsed.hash or parsed.href != normalized:
        raise ValueError('TT02-evidenslenken må være en absolutt HTTPS-lenke uten credentials, query eller fragment.')
    return parsed.href


def project(input):
    evidence = _object(input['evidence'])
    evidence_url = _safe_url(input.get('evidenceUrl'))
    organization = _required(input['expectedCompanyOrgNumber'], 'Forventet organisasjonsnummer')
    if not re.fullmatch(r'[0-9]{9}', organization) or _string(evidence.get('companyOrgNumber'), 'Organisasjonsnummer') != organization:
        raise ValueError('TT02-evidensens organisasjonsnummer matcher ikke selskapet.')
    if input['expectedIncomeYear'] != 2025 or evidence.get('incomeYear') != 2025:
        raise ValueError('TT02-evidensens inntektsår matcher ikke aktivt regnskapsår.')
    if evidence.get('schemaVersion') != 2 or evidence.get('status') != 'submitted_and_receipted':
        raise ValueError('TT02-evidensen må være ferdig innsendt med offisiell tilbakemelding.')
    if evidence.get('environment') != 'test':
        raise ValueError('Bare TT02 test-evidens kan importeres.')
    if evidence.get('productionEnabled') is not False:
        raise ValueError('TT02-evidens med produksjon aktivert kan ikke importeres.')
    if evidence.get('secretsStored') is not False:
        raise ValueError('TT02-evidensen kan ikke inneholde lagrede hemmeligheter.')
    if tuple(sorted(re.split(f'[{_SPACE}]+', _string(evidence.get('scope'), 'Scope')))) != _SCOPES:
        raise ValueError('TT02-evidensen bruker feil scope-sett for skattemelding.')
    if evidence.get('systemUserResource') != 'app_skd_formueinntekt-skattemelding-v2':
        raise ValueError('TT02-evidensen bruker feil systembrukerressurs for skattemelding.')
    validation = _object(evidence.get('localSchemaValidation'))
    schemas = validation.get('schemas')
    if validation.get('status') != 'passed' or not isinstance(schemas, (list, tuple)) or tuple(sorted(s for s in schemas if isinstance(s, str))) != _SCHEMAS:
        raise ValueError('TT02-evidensen mangler komplett lokal skjemavalidering.')
    validation = _object(evidence.get('authorityValidation'))
    reasons = validation.get('failureReasons')
    if validation.get('result') != 'validertOK' or not isinstance(reasons, (list, tuple)) or len(reasons) != 0:
        raise ValueError('TT02-evidensen mangler validertOK uten blokkerende feil.')
    validated_at = _instant(evidence.get('validatedAt'), 'Valideringstidspunkt')
    hashes = _object(evidence.get('payloadHashes'))
    hashes = {key: _string(hashes.get(key), label) for key, label in (
        ('skattemelding', 'Skattemeldingshash'), ('naeringsspesifikasjon', 'Næringsspesifikasjonshash'),
        ('validationEnvelope', 'Valideringskonvolutthash'), ('submissionEnvelope', 'Innsendingskonvolutthash'))}
    current_hash = _string(evidence.get('currentDocumentReferenceHash'), 'Gjeldende dokumentreferansehash')
    if not all(re.fullmatch(r'[0-9a-f]{64}', digest) for digest in (*hashes.values(), current_hash)):
        raise ValueError('TT02-evidensens payload-hasher er ugyldige.')
    instance = _object(evidence.get('instance'))
    instance_id = _string(instance.get('id'), 'Instans-id')
    envelope_id = _string(instance.get('envelopeDataId'), 'Konvoluttdata-id')
    if not re.fullmatch('[0-9]+/' + _UUID, instance_id) or not re.fullmatch(_UUID, envelope_id):
        raise ValueError('TT02-evidensens instans- eller konvoluttdata-id er ugyldig.')
    if instance.get('envelopeUploaded') is not True or instance.get('fileScanResult') != 'Clean':
        raise ValueError('TT02-evidensens innsendingskonvolutt er ikke ferdig og ren.')
    if instance.get('confirmationPrepared') is not True or instance.get('processTask') != 'confirmation':
        raise ValueError('TT02-evidensen mangler dokumentert personbekreftelse-handoff.')
    confirmation_at = _instant(evidence.get('confirmationPreparedAt'), 'Personbekreftelse-handoff-tidspunkt')
    confirmation_url = 'https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=' + instance_id
    if _string(evidence.get('confirmationUrl'), 'Bekreftelseslenke') != confirmation_url:
        raise ValueError('TT02-evidensens personbekreftelseslenke er ugyldig.')
    archive = 'https://platform.tt02.altinn.no/storage/api/v1/instances/' + instance_id
    receipt = _object(evidence.get('receipt'))
    receipt_id = _string(receipt.get('dataId'), 'Kvitteringsdata-id')
    receipt_hash = _string(receipt.get('contentSha256'), 'Kvitteringshash')
    size = receipt.get('byteLength')
    if not re.fullmatch(_UUID, receipt_id) or receipt.get('dataType') != 'tilbakemelding' or receipt.get('contentType') not in ('application/xml', 'text/xml') or isinstance(size, bool) or not isinstance(size, (int, float)) or size < 1 or not float(size).is_integer() or not re.fullmatch(r'[0-9a-f]{64}', receipt_hash):
        raise ValueError('TT02-evidensens offisielle tilbakemelding er ugyldig.')
    receipt_ref = _string(receipt.get('reference'), 'Kvitteringsreferanse')
    if receipt_ref != archive + '/data/' + receipt_id:
        raise ValueError('TT02-evidensens kvitteringsreferanse er ugyldig.')
    submission = _object(evidence.get('submission'))
    ended_at = _instant(submission.get('processEndedAt'), 'Prosesslutt')
    archived_at = _instant(submission.get('archivedAt'), 'Arkiveringstidspunkt')
    if submission.get('submitted') is not True or submission.get('archived') is not True or _string(submission.get('archiveReference'), 'Arkivreferanse') != archive:
        raise ValueError('TT02-evidensens innsending eller arkiv er ufullstendig.')
    retrieved_at = _instant(evidence.get('receiptRetrievedAt'), 'Tilbakemeldingshentetidspunkt')
    recorded_at = _instant(input['recordedAt'], 'Registreringstidspunkt') if 'recordedAt' in input else retrieved_at
    timeline = [('validering', validated_at), ('personbekreftelse-handoff', confirmation_at), ('prosesslutt', ended_at), ('arkivering', archived_at), ('tilbakemeldingshenting', retrieved_at)]
    for previous, current in zip(timeline, timeline[1:]):
        if _instant_order(previous[1]) > _instant_order(current[1]):
            raise ValueError(f'TT02-evidensens tidskronologi er ugyldig: {previous[0]} kan ikke være etter {current[0]}.')
    digest = hashlib.sha256('\n'.join(key + ':' + value for key, value in hashes.items()).encode()).hexdigest()
    company = _required(input['companyId'], 'Company id')
    actor = _required(input['recordedBy'], 'Recorded by')
    authority = {'company_id': company, 'obligation': 'skattemelding', 'environment': 'test', 'status': 'pending',
        'test_reference': 'tt02:' + instance_id,
        'feedback_summary': 'validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.',
        'receipt_reference': receipt_ref, 'archive_reference': archive, 'evidence_url': evidence_url,
        'payload_hash': 'sha256:' + digest, 'recorded_by': actor, 'recorded_at': recorded_at}
    calls = [{'endpoint': endpoint, 'body_hash': body_hash, 'idempotency_key': None, 'status': status, 'created_at': at} for endpoint, body_hash, status, at in (
        ('skatteetaten:company-tax-validation', hashes['validationEnvelope'], 'validertOK', validated_at),
        ('altinn:owner-confirmation-handoff', hashes['submissionEnvelope'], 'confirmation_prepared', confirmation_at),
        ('altinn:official-feedback-receipt', receipt_hash, 'received', retrieved_at))]
    return {'authorityRun': authority, 'submission': {
        'company_id': company, 'income_year': input['expectedIncomeYear'], 'filing': 'skattemelding for AS',
        'mode': 'test_authority', 'adapter_mode': 'test_authority', 'payload_hash': digest,
        'idempotency_key': f"company-tax:{company}:{input['expectedIncomeYear']}:{digest}",
        'status': 'feedback_ready', 'calls': calls, 'receipt_id': receipt_id, 'feedback_document_ids': [receipt_id],
        'feedback_items': [{'severity': 'warning', 'code': 'COMPANY_TAX_AUTHORITY_OUTCOME_PENDING',
            'message': 'Offisiell tilbakemelding er mottatt, men myndighetsutfallet venter på klassifisering.', 'documentId': receipt_id}],
        'receipt_metadata': {'authority': 'skatteetaten', 'receiptId': receipt_id, 'status': 'feedback_ready',
            'receivedAt': retrieved_at, 'feedbackDocumentIds': [receipt_id], 'dataType': 'tilbakemelding',
            'contentType': receipt['contentType'], 'byteLength': size, 'contentSha256': receipt_hash,
            'reference': receipt_ref, 'archiveReference': archive, 'processEndedAt': ended_at, 'archivedAt': archived_at},
        'submitted_payload_ref': {'companyOrgNumber': organization, 'incomeYear': input['expectedIncomeYear'],
            'envelopeDataId': envelope_id, 'archiveReference': archive, 'payloadHash': digest,
            'skattemeldingHash': hashes['skattemelding'], 'naeringsspesifikasjonHash': hashes['naeringsspesifikasjon'],
            'validationEnvelopeHash': hashes['validationEnvelope'], 'submissionEnvelopeHash': hashes['submissionEnvelope'],
            'currentDocumentReferenceHash': current_hash, 'storedAt': retrieved_at},
        'submitted_payload': None, 'failure_code': None, 'failure_message': None,
        'created_by': actor, 'submitted_by': None, 'updated_at': retrieved_at,
    }}
