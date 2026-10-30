"""Compose one owner-approved synthetic Accounts preparation scope on designated Preview."""
from datetime import UTC, datetime, timedelta
import json
import os
import re
from uuid import UUID

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from talli_backend.application.private_preview_accounts_signoff import (
    BOARD, MEETING, PrivatePreviewAccountsSignoff,
)

FLAG = 'TALLI_PREVIEW_SYNTHETIC_ACCOUNTS_SIGNOFF'
PROJECT = 'pkpyyxryfhfehrbhbynp'
COMPANY = '53454096-3fb6-45a6-a9c8-35fa83824614'
DECISION = '81883db6-cf34-4140-be2e-e8c7e7070a65'
DECISION_SHA256 = '8d6b6c12086eb4bb3c4adf5470630e1e81b92503a88d3997b2a67ba7999bceaf'
SOURCE_SHA256 = 'e9c9e448995b5d533a977a28eb085cb470432f231788e8fc87c158e17f49a93a'
UNSIGNED = {BOARD: 'e9751bd31ea0f01cadcfab06690d18f292400ceacebf2c6dbbbcc50da06c9866',
    MEETING: '4b135a1af3fbe42d863ba0a60ea8a4c2a54e1b7eb9f967d573eb7b65ac362608'}
CLOSED = {'TALLI_RF1086_PRODUCTION_ENABLED': 'false', 'TALLI_AUTHORITY_OPS_ENABLED': 'false',
    'TALLI_ANNUAL_BILLING_MODE': 'off', 'TALLI_ANNUAL_CHECKOUT_RECONCILIATION_MODE': 'off',
    'TALLI_VALIDATION_OBSERVATION_MODE': 'off', 'TALLI_COMPANY_TEST_RETENTION_MODE': 'off'}


def compose_preview_accounts_signoff(*, environment=None, now=None):
    env = os.environ if environment is None else environment
    raw = env.get(FLAG)
    if raw is None:
        return None
    clock = now or (lambda: datetime.now(UTC))
    try:
        if (len(raw) > 1024 or env.get('VERCEL') != '1' or env.get('VERCEL_ENV') != 'preview'
                or env.get('VERCEL_TARGET_ENV') != 'preview'
                or env.get('VERCEL_PROJECT_ID') != 'prj_u28yRnkslspXi3LSEDQHvTz8EWCD'
                or env.get('SUPABASE_URL') != 'https://' + PROJECT + '.supabase.co'
                or any(env.get(key) != expected for key, expected in CLOSED.items())):
            raise ValueError()
        registry = json.loads(env.get('TALLI_PREVIEW_SYNTHETIC_REGISTRY_IDENTITY', 'null'))
        if (type(registry) is not dict or registry.get('org_number') != '992803750'
                or registry.get('source') != 'browser_test'):
            raise ValueError()
        database = conninfo_to_dict(env.get('TALLI_LEDGER_DATABASE_URL', ''))
        host = database.get('host', '')
        if (database.get('service') or database.get('servicefile') or database.get('hostaddr')
                or any(env.get(key) for key in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR'))
                or not (host == 'db.' + PROJECT + '.supabase.co'
                    or re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com', host)
                        and database.get('user', '').endswith('.' + PROJECT))):
            raise ValueError()
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {'purpose', 'companyId', 'incomeYear', 'decisionId',
                'decisionSha256', 'sourceSha256', 'unsignedDocumentSha256', 'expiresAt'}
                or value['purpose'] != 'synthetic_accounts_draft_only_v1'
                or value['companyId'] != COMPANY or type(value['incomeYear']) is not int or value['incomeYear'] != 2025
                or value['decisionId'] != DECISION or value['decisionSha256'] != DECISION_SHA256
                or value['sourceSha256'] != SOURCE_SHA256 or value['unsignedDocumentSha256'] != UNSIGNED
                or str(UUID(value['companyId'])) != value['companyId']):
            raise ValueError()
        expires = datetime.fromisoformat(value['expiresAt'])
        if (expires.utcoffset() is None or expires <= clock() or expires > clock() + timedelta(hours=24)):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError, ProgrammingError):
        raise ValueError('Accounts sign-off simulation requires the designated finite synthetic Preview scope') from None
    return PrivatePreviewAccountsSignoff(COMPANY, DECISION, DECISION_SHA256, SOURCE_SHA256, UNSIGNED, expires, clock)
