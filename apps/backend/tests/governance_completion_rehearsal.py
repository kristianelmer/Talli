"""Pinned disposable SQL replay; never changes a released migration on disk."""
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
_RULE = json.loads((ROOT / 'tests/fixtures/governance_completion_replay.json').read_text())


def adapt_governance_completion_rehearsal(relative, source):
    if relative != 'migrations/' + _RULE['migration']:
        return source
    if (type(source) is not str or sha256(source.encode()).hexdigest() != _RULE['sourceSha256']
            or source.count(_RULE['before']) != 1):
        raise ValueError('governance_completion_rehearsal_source_drift')
    adapted = source.replace(_RULE['before'], _RULE['after'])
    if sha256(adapted.encode()).hexdigest() != _RULE['rehearsalSha256']:
        raise ValueError('governance_completion_rehearsal_source_drift')
    return adapted
