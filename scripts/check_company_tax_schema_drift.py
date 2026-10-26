"""Release-only public-source drift check. Runtime XML validation stays offline."""
from datetime import datetime, timezone
from hashlib import sha256
from importlib.resources import files
import json
import re
import signal
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas


HEAD = 'https://api.github.com/repos/Skatteetaten/skattemeldingen/git/ref/heads/master'
RAW = 'https://raw.githubusercontent.com/Skatteetaten/skattemeldingen/'
MAX_RESPONSE = 4 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError('Schema source redirects are forbidden.')


def _fetch(url):
    # Fixed public endpoints only; no inherited provider or GitHub credential.
    request = Request(url, headers={'User-Agent':'Talli-Tax-Schema-Drift/1', 'Accept':'application/json, text/plain'})
    with build_opener(_NoRedirect()).open(request, timeout=5) as response:
        value = response.read(MAX_RESPONSE + 1)
    if len(value) > MAX_RESPONSE:
        raise ValueError('Schema source response is too large.')
    return value


def verify_current(fetch=_fetch):
    validator = PinnedTax2025Schemas()  # Verify the local pin before any network.
    bundle = files('talli_backend.modules.company_tax_filing')/'schemas'/'2025'
    manifest_raw = (bundle/'manifest.json').read_bytes()
    if sha256(manifest_raw).hexdigest() != validator.schema_sha256:
        raise ValueError('Schema pin changed during the probe.')
    manifest = json.loads(manifest_raw)
    observed = json.loads(fetch(HEAD))
    if (not isinstance(observed, dict) or observed.get('ref') != 'refs/heads/master'
            or not isinstance(observed.get('object'), dict)
            or observed['object'].get('type') != 'commit'
            or type(observed['object'].get('sha')) is not str
            or re.fullmatch('[0-9a-f]{40}', observed['object']['sha']) is None):
        raise ValueError('Official source reference is unavailable.')
    current = observed['object']['sha']
    evidence = {}
    for name, expected in sorted(manifest['files'].items()):
        raw = fetch(RAW+current+'/'+expected['sourcePath'])
        if type(raw) is not bytes or len(raw) > MAX_RESPONSE:
            raise ValueError('Official source bytes are unavailable.')
        digest = sha256(raw).hexdigest()
        evidence[name] = {'sha256':digest, 'bytes':len(raw),
            'matches':digest == expected['sha256'] and len(raw) == expected['bytes']}
    return {'schema':'company-tax-schema-drift-v1',
        'status':'current' if all(row['matches'] for row in evidence.values()) else 'drift',
        'checkedAt':datetime.now(timezone.utc).isoformat(),
        'incomeYear':2025, 'schemaSha256':validator.schema_sha256,
        'approvedSourceCommit':manifest['sourceCommit'], 'observedSourceCommit':current,
        'completeEnumeration':True, 'files':evidence}


def main():
    if len(sys.argv) != 1:
        print(json.dumps({'status':'unavailable','reason':'arguments_forbidden','completeEnumeration':False}))
        return 2
    def deadline(*_):
        raise TimeoutError('Schema source deadline exceeded.')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(45)
    try:
        evidence = verify_current()
        print(json.dumps(evidence,sort_keys=True,separators=(',',':')))
        return 0 if evidence['status'] == 'current' else 1
    except Exception:
        # No upstream response bytes, XML, URLs from redirects or credential
        # configuration enter the release log on a failed/incomplete check.
        print(json.dumps({'schema':'company-tax-schema-drift-v1','status':'unavailable',
            'reason':'source_check_incomplete','completeEnumeration':False}))
        return 2
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
