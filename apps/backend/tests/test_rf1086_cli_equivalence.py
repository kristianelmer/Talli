"""Actual retained CLI processes compared with the captured original entry."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[3]
ORACLE=Path(__file__).parent/'fixtures/rf1086_oracle/cli-oracle.json'
CASES=json.loads(ORACLE.read_text())
FIXED_CLOCK='''from datetime import datetime,timezone,timedelta
import talli_backend.modules.shareholder_register_filing.offline as s
import holding_cli.main as c
class Clock(datetime):
 count=0
 @classmethod
 def now(cls,tz=None):
  value=datetime(2026,9,9,12,0,0,123456,tzinfo=timezone.utc)+timedelta(microseconds=cls.count);cls.count+=1;return value
s.datetime=Clock
raise SystemExit(c.main())
'''

@pytest.fixture(scope='module')
def cli_workspace(tmp_path_factory):
    path=tmp_path_factory.mktemp('rf-cli-equivalence')
    for family in ('rf1086','rf1086_invalid'):
        shutil.copytree(ROOT/'tests/fixtures'/family,path/'tests/fixtures'/family)
    return path


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['name'])
def test_retained_cli_stdout_stderr_exit_and_xsd(case,cli_workspace):
    assert shutil.which('xmllint'), 'official XSD validation is required for this integration proof'
    command=[sys.executable,'-c',FIXED_CLOCK] if case.get('fixed_clock') else [sys.executable,'-m','holding_cli.main']
    result=subprocess.run([*command,*case['argv']],cwd=cli_workspace,
        env={**os.environ,'PYTHONPATH':str(ROOT)},input=case['stdin'],text=True,capture_output=True,check=False)
    assert (result.returncode,result.stdout,result.stderr)==(case['exit_code'],case['stdout'],case['stderr'])


def test_built_cli_rejects_invalid_xml_with_original_diagnostic_path(cli_workspace):
    # Keep xmllint's caller-supplied XML path and first failure behavior even
    # though the byte-identical canonical schema is installed package data.
    (cli_workspace/'invalid.xml').write_text('<wrong />\n')
    result=subprocess.run([sys.executable,'-m','holding_cli.main','validate-rf1086-xml','--hovedskjema','invalid.xml','--underskjema','invalid.xml'],
        cwd=cli_workspace,env={**os.environ,'PYTHONPATH':str(ROOT)},text=True,capture_output=True,check=False)
    assert result.returncode==3
    assert "invalid.xml:1: element wrong: Schemas validity error" in result.stderr
    assert 'invalid.xml fails to validate' in result.stderr
    assert result.stdout==''


def test_retired_root_rf_implementation_has_no_fallback_imports():
    assert not any((ROOT/'holding_core'/name).exists() for name in ('models.py','readiness.py','rf1086.py','rf1086_codes.py','rf1086_submission.py'))
    cli=(ROOT/'holding_cli/main.py').read_text()
    assert 'holding_core.submission' not in cli and 'holding_core.models' not in cli
    assert 'talli_backend.modules.shareholder_register_filing.public' in cli
