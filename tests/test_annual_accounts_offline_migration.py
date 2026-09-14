"""Preserve the real offline API and CLI while Accounts policy changes owner."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from holding_core.annual import AnnualData, assess_annual_accounts_readiness, build_annual_accounts_payload, simulate_annual_accounts

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'architecture/evidence/issues/153'


class AnnualAccountsOfflineMigrationTest(unittest.TestCase):
    def test_original_offline_payload_readiness_and_simulation(self):
        captured = json.loads((EVIDENCE / 'characterization/legacy-offline-characterization.json').read_text())
        for case in captured['cases']:
            with self.subTest(case=case['id']):
                source = AnnualData.model_validate(case['input'])
                actual = {'payload': build_annual_accounts_payload(source).model_dump(mode='json'),
                    'readiness': assess_annual_accounts_readiness(source).model_dump(mode='json'),
                    'simulation': simulate_annual_accounts(source).model_dump(mode='json')}
                self.assertEqual(actual, case['output'])

    def test_original_cli_json_text_exit_and_errors(self):
        captured = json.loads((EVIDENCE / 'pure-calculation/legacy-cli-characterization.json').read_text())
        for case in captured['cases']:
            with self.subTest(args=case['args']):
                result = subprocess.run([sys.executable, '-m', 'holding_cli.main', *case['args']], cwd=ROOT,
                    env={'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin',
                         'PYTHONPATH': str(ROOT) + ':' + str(ROOT/'apps/backend/src')},
                    capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, case['exitCode'])
                self.assertEqual(result.stdout, case['stdout'])
                self.assertEqual(result.stderr, case['stderr'])


if __name__ == '__main__':
    unittest.main()
