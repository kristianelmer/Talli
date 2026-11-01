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
    NativeArchive, compile_program, verify_managed_triggers,
)


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
            capture = SimpleNamespace(schemas={'public'}, catalog={'constraints': []},
                custom_roles=[], rows={'auth.users': {'rows': 0}}, roles={'memberships': []})
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
            print('PASS: real dump labels custom Auth trigger with provider table owner; '
                'exact native declaration matches; missing/changed/disabled/replica/always '
                'destination triggers rejected; non-normal source enable states rejected')
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
