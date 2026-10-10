"""Both disposable replay consumers use identical, narrowly adapted SQL bytes."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from governance_completion_rehearsal import adapt_governance_completion_rehearsal


ROOT = Path(__file__).resolve().parents[3]
RULE = json.loads((ROOT / 'tests/fixtures/governance_completion_replay.json').read_text())
RELATIVE = 'migrations/' + RULE['migration']
SOURCE = (ROOT / 'supabase' / RELATIVE).read_text()


def test_python_and_node_rehearsals_emit_the_same_pinned_bytes():
    actual = adapt_governance_completion_rehearsal(RELATIVE, SOURCE)
    script = """
import { readFileSync } from 'node:fs';
import { adaptGovernanceCompletionRehearsal } from './tests/support/governance_completion_rehearsal.mjs';
const relative = process.argv[1];
process.stdout.write(adaptGovernanceCompletionRehearsal(relative, readFileSync('supabase/' + relative, 'utf8')));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script, RELATIVE],
                            cwd=ROOT, check=True, capture_output=True, text=True)
    assert actual == result.stdout
    assert sha256(actual.encode()).hexdigest() == RULE['rehearsalSha256']
    assert actual.replace(RULE['after'], RULE['before']) == SOURCE
    assert (ROOT / 'supabase' / RELATIVE).read_text() == SOURCE


@pytest.mark.parametrize('changed', [SOURCE + '\n', SOURCE.replace(RULE['before'], ''), None])
def test_changed_frozen_sql_is_not_replayed(changed):
    with pytest.raises(ValueError, match='^governance_completion_rehearsal_source_drift$'):
        adapt_governance_completion_rehearsal(RELATIVE, changed)


def test_adaptation_requires_original_input_and_leaves_other_files_unchanged():
    adapted = adapt_governance_completion_rehearsal(RELATIVE, SOURCE)
    with pytest.raises(ValueError, match='^governance_completion_rehearsal_source_drift$'):
        adapt_governance_completion_rehearsal(RELATIVE, adapted)
    for relative in ('rollback/' + RULE['migration'], 'migrations/unknown.sql'):
        assert adapt_governance_completion_rehearsal(relative, SOURCE) == SOURCE
