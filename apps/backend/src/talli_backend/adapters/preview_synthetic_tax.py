"""Opt-in local Tax preparation. These bytes are synthetic, never authority observations."""
import base64
from datetime import datetime, UTC, timedelta
import json
import os
import re

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.application.private_preview_tax_preparation import PrivatePreviewTaxPreparation, ORGANIZATION
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCurrentDocumentReader, CompanyTaxError, TaxCurrentDocumentResponse, company_tax_authority_adapter,
)
from talli_backend.shared.kernel import IncomeYear, Timestamp

_FLAG = 'TALLI_PREVIEW_SYNTHETIC_TAX_PREPARATION'
_PROJECT = 'pkpyyxryfhfehrbhbynp'
_CLOSED = {'TALLI_RF1086_PRODUCTION_ENABLED':'false', 'TALLI_AUTHORITY_OPS_ENABLED':'false',
    'TALLI_ANNUAL_BILLING_MODE':'off', 'TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE':'off',
    'TALLI_VALIDATION_OBSERVATION_MODE':'off', 'TALLI_COMPANY_TEST_RETENTION_MODE':'off'}
_TAX = (b'<?xml version="1.0" encoding="UTF-8"?><skattemelding '
    b'xmlns="urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5">'
    b'<partsnummer>0</partsnummer><inntektsaar>2025</inntektsaar></skattemelding>')
_ORIGINAL = (b'<?xml version="1.0" encoding="UTF-8"?><skattemeldingOgNaeringsspesifikasjonforespoerselResponse '
    b'xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2">'
    b'<dokumenter><skattemeldingdokument><id>synthetic-private-preview-992803750-2025-v1</id>'
    b'<encoding>utf-8</encoding><content>' + base64.b64encode(_TAX) +
    b'</content><type>skattemeldingUpersonligUtkast</type></skattemeldingdokument></dokumenter>'
    b'</skattemeldingOgNaeringsspesifikasjonforespoerselResponse>')


@company_tax_authority_adapter(CompanyTaxCurrentDocumentReader)
class SyntheticPreviewCurrentDocument:
    async def fetch_current_document(self, *, income_year, company_org_number):
        if income_year != 2025 or company_org_number != ORGANIZATION:
            raise CompanyTaxError.forbidden()
        return TaxCurrentDocumentResponse(ORGANIZATION, IncomeYear(2025),
            base64.b64encode(_ORIGINAL).decode('ascii'), Timestamp(datetime.now(UTC)))


def compose_preview_tax_preparation(access, *, environment=None, now=None):
    env = os.environ if environment is None else environment
    raw = env.get(_FLAG)
    if raw is None:
        return None
    clock = now or (lambda: datetime.now(UTC))
    try:
        if (env.get('VERCEL') != '1' or env.get('VERCEL_ENV') != 'preview'
                or env.get('VERCEL_TARGET_ENV') != 'preview'
                or env.get('VERCEL_PROJECT_ID') != 'prj_u28yRnkslspXi3LSEDQHvTz8EWCD'
                or env.get('SUPABASE_URL') != 'https://' + _PROJECT + '.supabase.co'
                or any(env.get(k) != v for k,v in _CLOSED.items()) or len(raw) > 512):
            raise ValueError()
        registry = json.loads(env.get('TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY', 'null'))
        if not isinstance(registry, dict) or registry.get('org_number') != ORGANIZATION or registry.get('source') != 'browser_test':
            raise ValueError()
        database = conninfo_to_dict(env.get('TALLI_LEDGER_DATABASE_URL', ''))
        host = database.get('host', '')
        if (database.get('service') or database.get('servicefile') or database.get('hostaddr')
                or any(env.get(k) for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR'))
                or not (host == 'db.' + _PROJECT + '.supabase.co'
                    or re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com', host)
                        and database.get('user','').endswith('.' + _PROJECT))):
            raise ValueError()
        value = json.loads(raw)
        if set(value) != {'purpose','expiresAt'} or value['purpose'] != 'synthetic_preparation_only_v1':
            raise ValueError()
        expires = datetime.fromisoformat(value['expiresAt'])
        if expires.utcoffset() is None or expires > clock() + timedelta(hours=24):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError, ProgrammingError):
        raise ValueError('Tax preparation requires the designated finite synthetic Preview scope') from None
    # A cold start after expiry must still serve durable archives and health.
    if expires <= clock():
        return None
    schemas = PinnedTax2025Schemas()
    return lambda token: PrivatePreviewTaxPreparation(SyntheticPreviewCurrentDocument(), schemas,
        access, token, expires, now=clock)
