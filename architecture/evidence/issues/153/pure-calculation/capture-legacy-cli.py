"""Actual local CLI stdout/stderr/exit capture before replacing offline policy."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

assert sys.version_info[:3] == (3, 12, 12)
root = Path.cwd()
baseline = '5b74340ca75f215b43d754c6bf0fc49ef5974b0b'
sources = {}
for name in ('holding_cli/main.py', 'holding_core/annual.py', 'holding_core/validation.py'):
    raw = (root/name).read_bytes()
    assert raw == subprocess.check_output(['git', 'show', f'{baseline}:{name}'])
    sources[name] = hashlib.sha256(raw).hexdigest()
fixture_dir = 'tests/fixtures/annual_validation/'
groups = [[], ['simple_holding_pass.json'], ['simple_holding_mismatch.json'], ['simple_holding_blocked.json'], ['unsupported_group_contribution.json'], ['simple_holding_pass.json', 'simple_holding_mismatch.json'], ['__accounts153_missing__.json']]
assert not (root/fixture_dir/'__accounts153_missing__.json').exists()
cases = []
for group in groups:
    for as_json in (False, True):
        args = ['validate-annual-public-data']
        for fixture in group:
            args.extend(['--case', fixture_dir + fixture])
        if as_json:
            args.append('--json')
        result = subprocess.run([sys.executable, '-m', 'holding_cli.main', *args], cwd=root,
            env={'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin',
                 'PYTHONPATH': str(root) + ':' + str(root/'apps/backend/src')},
            capture_output=True, text=True, check=False)
        cases.append({'args': args, 'exitCode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
data = {'schemaVersion': '1.0', 'sourceRevision': baseline, 'runtime': sys.version,
        'sources': sources, 'scope': 'Actual local CLI, public/synthetic fixtures only; no provider/environment credentials.', 'cases': cases}
raw = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
with Path(sys.argv[1]).open('xb') as output:
    output.write(raw)
print(json.dumps({'cases': len(cases), 'exitCodes': [c['exitCode'] for c in cases], 'sha256': hashlib.sha256(raw).hexdigest()}))
