"""Disposable PG17 parses and contains the finite Preview draft admission DDL."""
from pathlib import Path

import psycopg
import pytest

from test_annual_accounts_delivery_events_database import event_database, accounts_database, draft, draft_database, database

pytestmark = pytest.mark.accounts_database
ROOT = Path(__file__).resolve().parents[3]
ACTIVATE = ROOT / 'supabase/private-preview/20261030180000_synthetic_accounts_draft_only.sql'
CONTAIN = ROOT / 'supabase/private-preview/20261030180100_contain_synthetic_accounts_draft.sql'


def test_finite_synthetic_accounts_sql_preserves_roles_and_restores_reader_first(event_database):
    with psycopg.connect(**event_database, user='postgres', autocommit=True) as db:
        db.execute('''
          create schema if not exists corporate_governance;
          create table corporate_governance.annual_close_decisions(
            id uuid, company_id uuid, income_year integer, source_hash text, decision_hash text);
          create table corporate_governance.annual_close_artifacts(
            decision_id uuid, artifact_kind text, content_sha256 text, variant text);
          create table corporate_governance.annual_close_finalizations(decision_id uuid);
        ''')
        memberships = 'select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before = db.execute(memberships).fetchall()
        db.execute(ACTIVATE.read_text())
        assert db.execute(memberships).fetchall() == before
        marker = db.execute("select prosrc from pg_proc where oid='annual_accounts_filing.delivery_draft_writes_enabled_v1()'::regprocedure").fetchone()[0]
        assert '2026-10-30 18:00:00+00' in marker
        assert db.execute("select count(*) from pg_trigger where tgrelid='annual_accounts_filing.delivery_drafts'::regclass and tgname='accounts_synthetic_preview_draft_admission'").fetchone()[0] == 1
        assert db.execute("select prosrc from pg_proc where oid='annual_accounts_filing.delivery_operations_enabled_v1()'::regprocedure").fetchone()[0] == 'begin return false; end;'
        db.execute(CONTAIN.read_text())
        assert db.execute(memberships).fetchall() == before
        assert db.execute("select prosrc from pg_proc where oid='annual_accounts_filing.delivery_draft_writes_enabled_v1()'::regprocedure").fetchone()[0] == 'begin return false; end;'
        assert db.execute("select count(*) from pg_trigger where tgrelid='annual_accounts_filing.delivery_drafts'::regclass and tgname='accounts_synthetic_preview_draft_admission'").fetchone()[0] == 0
