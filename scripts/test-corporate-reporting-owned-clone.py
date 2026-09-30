"""Run destructive reporting rehearsals in a fresh clone of the owned local stack.

The source is identified by the aggregate runner's explicit workdir, never by a
discovered database or a reusable template. Cluster role changes remain serial.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
SUITE = "apps/backend/tests/test_corporate_reporting_year_database_runtime.py"


def owned_source(workdir, database_url, inspect):
    """Validate both the explicit workdir and the running container binding."""
    path = Path(workdir).resolve(strict=True)
    if not path.name.startswith("talli-supabase-local."):
        raise ValueError("Reporting clone requires an owned isolated Supabase workdir")
    config = tomllib.loads((path / "supabase/config.toml").read_text())
    project = config["project_id"]
    if not re.fullmatch(r"tallig[0-9]+", project):
        raise ValueError("Reporting clone requires an isolated Supabase project")
    info = conninfo_to_dict(database_url)
    if (info.get("host") not in ("127.0.0.1", "localhost", "::1")
            or "hostaddr" in info or info.get("dbname") != "postgres"
            or info.get("user") != "postgres"
            or info.get("port") != str(config["db"]["port"])):
        raise ValueError("DATABASE_URL must identify the owned local source")
    name = "supabase_db_" + project
    container = inspect(name)
    bindings = container.get("NetworkSettings", {}).get("Ports", {}).get("5432/tcp", []) or []
    if (container.get("Name") != "/" + name
            or not container.get("State", {}).get("Running")
            or not any(binding.get("HostPort") == info["port"]
                       and binding.get("HostIp") in ("127.0.0.1", "0.0.0.0", "::", "::1")
                       for binding in bindings)):
        raise ValueError("Owned Supabase container does not match DATABASE_URL")
    return container["Id"], info["dbname"]


def inspect_container(name):
    return json.loads(subprocess.check_output(["docker", "inspect", name]))[0]


def verify_source_session(source_url, container):
    # A remote Docker context can publish the same numeric port on another
    # machine. Observe this exact live source connection inside the pinned
    # container before authorizing dump/create/drop there.
    marker = "rf193_clone_" + uuid4().hex
    with psycopg.connect(source_url, application_name=marker) as connection:
        pid = connection.execute("select pg_backend_pid()").fetchone()[0]
        query = ("select count(*) from pg_stat_activity where datname='postgres' "
                 f"and usename='postgres' and pid={int(pid)} and application_name='{marker}'")
        observed = subprocess.check_output(["docker", "exec", container, "psql", "-U", "supabase_admin",
                                            "--dbname", "postgres", "-XAt", "-c", query], text=True).strip()
        if observed != "1":
            raise ValueError("DATABASE_URL is not served by the owned Supabase container")


def role_memberships(source_url):
    with psycopg.connect(source_url) as connection:
        return connection.execute(
            "select roleid,member,grantor,admin_option,inherit_option,set_option "
            "from pg_auth_members order by roleid,member,grantor"
        ).fetchall()


def main():
    source_url = os.environ.get("DATABASE_URL", "")
    workdir = os.environ.get("TALLI_SUPABASE_WORKDIR")
    if not workdir or not source_url:
        raise ValueError("DATABASE_URL and TALLI_SUPABASE_WORKDIR are required")
    container, source_name = owned_source(workdir, source_url, inspect_container)
    verify_source_session(source_url, container)
    original_memberships = role_memberships(source_url)
    clone = "rf193_governance_" + uuid4().hex
    clone_url = make_conninfo(source_url, dbname=clone)
    created = False
    # Use the pinned container ID throughout so a restarted/replaced container
    # cannot silently become the source or cleanup target.
    docker = ["docker", "exec", "-i", container]
    with tempfile.TemporaryFile() as dump:
        subprocess.run(docker + ["pg_dump", "-U", "supabase_admin", "--format=custom",
                                 "--dbname", source_name], stdout=dump, check=True)
        try:
            subprocess.run(docker + ["createdb", "-U", "supabase_admin", "--template=template0", clone], check=True)
            created = True
            dump.seek(0)
            subprocess.run(docker + ["pg_restore", "-U", "supabase_admin", "--exit-on-error",
                                     "--dbname", clone], stdin=dump, check=True)
            result = subprocess.run([sys.executable, "-m", "pytest", "-c", "apps/backend/pyproject.toml", SUITE, "-q"],
                                    cwd=ROOT, env={**os.environ, "DATABASE_URL": clone_url})
            return result.returncode
        finally:
            if created:
                # This random name was created by this invocation. Never clean
                # an existing database, infer a clone, or broaden the target.
                subprocess.run(docker + ["dropdb", "-U", "supabase_admin", "--force", clone], check=True)
            if role_memberships(source_url) != original_memberships:
                raise RuntimeError("Reporting clone rehearsal changed cluster role memberships")


if __name__ == "__main__":
    raise SystemExit(main())
