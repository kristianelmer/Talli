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


@pytest.mark.parametrize('body_fails', [False, True])
def test_historical_approval_fixture_restores_all_successors_with_pinned_sql(monkeypatch, body_fails):
    import test_rf1086_source_approval_database as approval
    from test_authority_connections_database_runtime import RF193_CONSEQUENTIAL

    successors = [layer['migration'] for layer in RF193_CONSEQUENTIAL
                  if layer['migration'] > approval.MIGRATION]
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            calls.append(statement)

    monkeypatch.setattr(approval.psycopg, 'connect', lambda *args, **kwargs: Connection())
    monkeypatch.setattr(approval, 'rf193_consequential_topology', lambda db: successors)
    fixture = approval.historical_source_command_revision.__wrapped__()
    next(fixture)
    if body_fails:
        with pytest.raises(RuntimeError, match='^historical body failed$'):
            fixture.throw(RuntimeError('historical body failed'))
    else:
        fixture.close()

    assert len(calls) == 2 + len(successors)
    for name, statement in zip(successors, calls[2:], strict=True):
        expected = (ROOT / 'supabase/migrations' / name).read_text()
        if name == RULE['migration']:
            assert sha256(statement.encode()).hexdigest() == RULE['rehearsalSha256']
        else:
            assert statement == expected
