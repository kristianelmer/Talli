"""Closed predecessor replay preserves RF authority or rejects drift explicitly."""
from pathlib import Path

import pytest

import documents_rf_guard_replay_fixture as fixture


def sources():
    directory = fixture.ROOT / "supabase/migrations"
    return (directory / fixture.PREDECESSOR).read_bytes(), (directory / fixture.WITHDRAWAL).read_bytes()


def installed_catalog():
    predecessor, _ = sources()
    text = predecessor.decode("utf-8")
    statement = text[text.index(fixture.START):]
    body = statement.split("$fn$")[1]
    body = body.replace(fixture.ANCHOR, fixture.ANCHOR + "\n " + fixture.GUARD)
    return (1234, "shareholder_register_filing_store_owner", body, "owner/Gov ACL",
            ['search_path=""'], True, "v", "u", "plpgsql", "void", "complete installed definition")


class Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class ReplayDatabase:
    def __init__(self, before=None, after=None):
        self.before = installed_catalog() if before is None else before
        self.after = self.before if after is None else after
        self.queries = []
        self.replays = []

    def execute(self, sql, params=None):
        if params is not None:
            assert params == (fixture.IDENTITY,)
            self.queries.append(sql)
            return Cursor(self.after if self.replays else self.before)
        self.replays.append(sql)
        return Cursor(None)


def test_omission_inverts_to_exact_published_migration_and_keeps_acl_role_operations():
    predecessor, withdrawal = sources()
    adapted, body = fixture._replay_sql(predecessor, withdrawal)
    predecessor = predecessor.decode("utf-8")
    start = predecessor.index(fixture.START)
    end = predecessor.index(fixture.END, start) + len(fixture.END)
    assert adapted.replace(fixture.OMISSION, predecessor[start:end]) == predecessor
    assert adapted.count(fixture.OMISSION) == 1
    assert fixture.START not in adapted
    assert body == installed_catalog()[2]
    for statement in (
        "revoke all on function shareholder_register_filing.lock_company_write_v1",
        "grant execute on function shareholder_register_filing.assert_current_register_observation_v1",
        "do $wrap$", "do $restore$", "commit;",
    ):
        assert statement in adapted


def test_valid_installed_assertion_is_checked_before_and_after_one_replay():
    db = ReplayDatabase()
    fixture.replay_documents_guards_preserving_rf_withdrawal(db)
    assert len(db.queries) == 2 and len(db.replays) == 1
    assert db.replays[0] == fixture._replay_sql(*sources())[0]


@pytest.mark.parametrize("field,value", [
    (1, "wrong_owner"), (2, "missing guard"), (4, None),
    (4, ['search_path=public']), (5, False), (6, "s"),
    (7, "s"), (8, "sql"), (9, "text"),
])
def test_installed_authority_or_body_drift_rejects_before_migration(field, value):
    before = list(installed_catalog())
    before[field] = value
    db = ReplayDatabase(before=tuple(before))
    with pytest.raises(AssertionError, match="installed_rf_assertion_drift"):
        fixture.replay_documents_guards_preserving_rf_withdrawal(db)
    assert len(db.queries) == 1 and db.replays == []


def test_missing_assertion_rejects_before_migration():
    db = ReplayDatabase()
    db.before = None
    with pytest.raises(AssertionError, match="installed_rf_assertion_drift"):
        fixture.replay_documents_guards_preserving_rf_withdrawal(db)
    assert db.replays == []


@pytest.mark.parametrize("field", range(11))
def test_complete_catalog_change_after_replay_is_detected(field):
    after = list(installed_catalog())
    after[field] = "changed"
    db = ReplayDatabase(after=tuple(after))
    with pytest.raises(AssertionError, match="rf_catalog_drift"):
        fixture.replay_documents_guards_preserving_rf_withdrawal(db)
    assert len(db.queries) == 2 and len(db.replays) == 1


@pytest.mark.parametrize("migration", [fixture.PREDECESSOR, fixture.WITHDRAWAL])
@pytest.mark.parametrize("mutation", ["append", "crlf"])
def test_source_drift_rejects_before_any_catalog_or_migration_io(tmp_path, monkeypatch, migration, mutation):
    directory = tmp_path / "supabase/migrations"
    directory.mkdir(parents=True)
    for name, content in zip((fixture.PREDECESSOR, fixture.WITHDRAWAL), sources(), strict=True):
        if name == migration:
            content = content + b"\n-- drift\n" if mutation == "append" else content.replace(b"\n", b"\r\n")
        (directory / name).write_bytes(content)
    monkeypatch.setattr(fixture, "ROOT", Path(tmp_path))
    db = ReplayDatabase(before=("unused",))
    with pytest.raises(AssertionError, match="documents_guard_replay_(predecessor|withdrawal)_drift"):
        fixture.replay_documents_guards_preserving_rf_withdrawal(db)
    assert db.queries == [] and db.replays == []
