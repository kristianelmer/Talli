"""Local workspace rehearsal: real RF API/storage, all provider effects disabled."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    fixture_root = Path(__file__).resolve().parent
    guards = runpy.run_path(str(fixture_root / 'start_shareholder_register_filing_backend.py'))
    for key in ('DATABASE_URL', 'TALLI_LEDGER_DATABASE_URL', 'TALLI_COMPANY_ACCESS_DATABASE_URL'):
        guards['loopback_url'](os.environ[key], ('postgres', 'postgresql'))
    guards['loopback_url'](os.environ['SUPABASE_URL'], ('http',))
    if any(os.environ.get(key) != 'false' for key in ('TALLI_RF1086_PRODUCTION_ENABLED', 'TALLI_AUTHORITY_OPS_ENABLED')):
        raise SystemExit('workspace_fixture_provider_activation_forbidden')
    if any(key.startswith(('TALLI_PROD_', 'TALLI_TEST_MASKINPORTEN_')) for key in os.environ):
        raise SystemExit('workspace_fixture_provider_credentials_forbidden')
    sys.addaudithook(guards['guard_socket'])
    runpy.run_path(str(fixture_root / 'start_talli_backend.py'), run_name='__main__')


if __name__ == '__main__':
    main()
