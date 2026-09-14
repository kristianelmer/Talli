"""Fixed test-only JSON driver; no network, persistence or dynamic dispatch."""
from collections.abc import Mapping
import dataclasses
import json
import math
import sys

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsCandidate, AnnualAccountsCorporateReadiness, AnnualAccountsEvidenceInput,
    AnnualAccountsReadinessIssue, AnnualAccountsRenderInput, AnnualAccountsSource,
    assess_annual_accounts_readiness, build_annual_accounts,
    import_annual_accounts_evidence, render_annual_accounts,
)


def plain(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if dataclasses.is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def source(value):
    return AnnualAccountsSource(value['incomeYear'], value['annualData'], tuple(value['ledgerEntries']))


def invoke(operation, value):
    if operation == 'payload':
        result = build_annual_accounts(source(value))
        return dict(schemaType=result.schema_type, hovedskjemaDataFormatId=result.main_form_format_id,
                    hovedskjemaDataFormatVersion=result.main_form_format_version,
                    selskapsregnskapDataFormatId=result.accounts_format_id,
                    selskapsregnskapDataFormatVersion=result.accounts_format_version,
                    notes=result.notes, fields=result.fields, feedback=result.feedback)
    if operation == 'render':
        payload = value['payload']
        candidate = AnnualAccountsCandidate(payload['schemaType'], payload['hovedskjemaDataFormatId'],
            payload['hovedskjemaDataFormatVersion'], payload['selskapsregnskapDataFormatId'],
            payload['selskapsregnskapDataFormatVersion'], payload.get('notes', {}),
            tuple(payload['fields']), tuple(payload['feedback']))
        result = render_annual_accounts(AnnualAccountsRenderInput(candidate, value['companyOrgNumber'],
            value['companyName'], value['contactEmail'], value['approvalDate'], value['confirmingRepresentative']))
        return dict(mainFormXml=result.main_form_xml, companyAccountsXml=result.company_accounts_xml)
    if operation == 'readiness':
        corporate = value.get('corporateDocuments')
        if corporate is not None:
            corporate = AnnualAccountsCorporateReadiness(corporate['enabled'], tuple(
                AnnualAccountsReadinessIssue(**issue) for issue in corporate['blockers']))
        return dict(companyId=value['companyId'], incomeYear=value['incomeYear'],
                    issues=assess_annual_accounts_readiness(source(value), company_id=value['companyId'], corporate=corporate))
    if operation == 'evidence':
        return import_annual_accounts_evidence(AnnualAccountsEvidenceInput(value['companyId'],
            value['expectedCompanyOrgNumber'], value['evidence'], value['recordedBy'],
            value['recordedAt'], value.get('evidenceUrl')))
    raise ValueError('Unknown fixed Accounts test operation.')


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('Accounts fixture exceeds the test-driver input limit.')
        request = json.loads(raw)
        response = {'value': plain(invoke(request['operation'], request['input']))}
    except Exception as error:
        response = {'error': str(error)}
    print(json.dumps(response, ensure_ascii=True, allow_nan=False))
