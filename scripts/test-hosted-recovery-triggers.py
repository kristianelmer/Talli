#!/usr/bin/env python3
"""Opt-in native PostgreSQL trigger regression; no hosted connections or credentials.

Uses installed PostgreSQL >=17 binaries and psycopg. Owns one temporary cluster
with only a private Unix socket, and stops it before removing its directory.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/backend/src'))
from talli_backend.adapters.hosted_recovery_sql import (
    NativeArchive, compile_program, execute_data, verify_managed_triggers,
)
from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery


def run(arguments, **kwargs):
    result = subprocess.run([str(value) for value in arguments], capture_output=True,
        timeout=30, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


def exercise(binaries, pg_restore, folder):
    data, socket = folder / 'database', folder / 'socket'
    socket.mkdir(mode=0o700)
    run([binaries / 'initdb', '-D', data, '-U', 'postgres', '--auth-local=trust',
        '--no-locale', '--encoding=UTF8'])
    run([binaries / 'pg_ctl', '-D', data, '-l', folder / 'server.log', '-o',
        f"-k {socket} -c listen_addresses='' -p 55439", '-w', 'start'])
    try:
        with psycopg.connect(host=str(socket), port=55439, user='postgres',
                dbname='postgres') as db:
            db.execute('create role supabase_auth_admin; create schema auth; '
                'create table auth.users(id int); '
                'alter table auth.users owner to supabase_auth_admin; '
                'create function public.custom_hook() returns trigger language plpgsql '
                'as $$begin return new; end$$; '
                'create trigger custom_hook after insert on auth.users '
                'for each row execute function public.custom_hook()')
            db.commit()
            raw = run([binaries / 'pg_dump', '-h', socket, '-p', '55439', '-U',
                'postgres', '-d', 'postgres', '-Fc'])
            archive = NativeArchive(SimpleNamespace(read=lambda _: raw),
                pg_restore=pg_restore, work=folder)
            entries = [entry for entry in archive.entries if entry.kind == 'TRIGGER']
            assert len(entries) == 1 and entries[0].owner == 'supabase_auth_admin'
            capture = SimpleNamespace(schemas={'public'}, application_schemas={'public'},
                profile={'tables': [['auth', 'users']]},
                access={'schemas': [['public', 'postgres', []]], 'relations': []},
                catalog={'constraints': []}, custom_roles=[],
                rows={'auth.users': {'rows': 0}}, roles={'memberships': []})
            program = compile_program(capture, archive)
            assert len(program.managed_triggers) == 1
            verify_managed_triggers(db, program.managed_triggers)
            for mutation in (
                'alter table auth.users disable trigger custom_hook',
                'alter table auth.users enable replica trigger custom_hook',
                'alter table auth.users enable always trigger custom_hook',
                'drop trigger custom_hook on auth.users; create trigger custom_hook '
                    'after delete on auth.users for each row execute function public.custom_hook()',
                'drop trigger custom_hook on auth.users',
            ):
                db.execute(mutation)
                try:
                    verify_managed_triggers(db, program.managed_triggers)
                except ValueError as error:
                    assert str(error) == 'hosted_managed_trigger_profile_changed'
                else:
                    raise AssertionError('changed or missing managed trigger accepted')
            db.execute('create trigger custom_hook after insert on auth.users '
                'for each row execute function public.custom_hook()')
            for mode in ('disable', 'enable replica', 'enable always'):
                db.execute(f'alter table auth.users {mode} trigger custom_hook')
                db.commit()
                altered = run([binaries / 'pg_dump', '-h', socket, '-p', '55439',
                    '-U', 'postgres', '-d', 'postgres', '-Fc'])
                changed = NativeArchive(SimpleNamespace(read=lambda _: altered),
                    pg_restore=pg_restore, work=folder)
                try:
                    compile_program(capture, changed)
                except ValueError as error:
                    assert str(error) == 'hosted_managed_trigger_definition_unsupported'
                else:
                    raise AssertionError('unsupported source trigger state accepted')
            # An empty UPDATE still fires statement triggers. Quarantine of an
            # empty capture must avoid it and need no authority to ALTER an
            # already disabled pre-provisioned role.
            db.execute('alter table auth.users alter column id type uuid using null::uuid; '
                'alter table auth.users add column banned_until timestamptz; '
                'create table public.quarantine_updates(value int); '
                'create function public.quarantine_statement()returns trigger language plpgsql '
                'as $$begin insert into public.quarantine_updates values(1);return null;end$$; '
                'create trigger quarantine_statement after update on auth.users '
                'for each statement execute function public.quarantine_statement(); '
                'create role quarantine_reader; create role quarantine_preprovisioned nologin; '
                'grant usage on schema auth to quarantine_reader; '
                'grant select(id),update(banned_until)on auth.users to quarantine_reader; '
                'grant insert on public.quarantine_updates to quarantine_reader')
            db.execute('set local role quarantine_reader')
            db.execute("update auth.users set banned_until='9999-12-31' where id=any('{}'::uuid[])")
            db.execute('reset role')
            assert db.execute('select count(*)from public.quarantine_updates').fetchone()[0] == 1
            db.execute('truncate public.quarantine_updates;set local role quarantine_reader')
            try:
                with db.transaction():
                    db.execute('alter role quarantine_preprovisioned nologin')
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError('fixture unexpectedly has ALTER ROLE authority')
            HostedBackupRecovery.__new__(HostedBackupRecovery)._quarantine(db,
                {'actors': [], 'logins': ['quarantine_preprovisioned']})
            db.execute('reset role')
            assert db.execute('select count(*)from public.quarantine_updates').fetchone()[0] == 0
            db.execute('create table public.copy_self_reference('
                'id int primary key,parent int references public.copy_self_reference(id))')
            execute_data(db, b'COPY public.copy_self_reference (id,parent) FROM stdin;\n'
                b'2\t1\n1\t\\N\n\\.\n', {'public.copy_self_reference': {'rows': 2}},
                order_by_foreign_keys=True)
            assert db.execute('select count(*)from public.copy_self_reference').fetchone()[0] == 2
            print('PASS: real dump labels custom Auth trigger with provider table owner; '
                'exact native declaration matches; missing/changed/disabled/replica/always '
                'destination triggers rejected; non-normal source enable states rejected; '
                'empty quarantine fires no statement trigger and needs no ALTER ROLE authority; '
                'self-referencing COPY validates its child-before-parent rows')
    finally:
        run([binaries / 'pg_ctl', '-D', data, '-m', 'fast', '-w', 'stop'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, required=True)
    parser.add_argument('--pg-restore', type=Path, required=True)
    args = parser.parse_args()
    if any(name.startswith('PG') and value for name, value in os.environ.items()):
        raise RuntimeError('inherited PostgreSQL connection settings are unsupported')
    with tempfile.TemporaryDirectory(prefix='talli-trigger-', dir=Path('/tmp').resolve()) as scratch:
        exercise(args.pg_bin.resolve(), args.pg_restore.resolve(), Path(scratch))
