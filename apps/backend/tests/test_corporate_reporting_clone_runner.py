"""The CI reporting lane cannot clone or clean an inferred database."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("reporting_clone_runner", ROOT / "scripts/test-corporate-reporting-owned-clone.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture
def source(tmp_path):
    workdir = tmp_path / "talli-supabase-local.owned"
    (workdir / "supabase").mkdir(parents=True)
    (workdir / "supabase/config.toml").write_text('project_id = "tallig123"\n[db]\nport = 55001\n')
    url = "postgresql://postgres:local@127.0.0.1:55001/postgres"
    container = {"Id": "owned-container-id", "Name": "/supabase_db_tallig123", "State": {"Running": True},
                 "NetworkSettings": {"Ports": {"5432/tcp": [{"HostPort": "55001", "HostIp": "0.0.0.0"}]}}}
    return workdir, url, container


def test_exact_running_workdir_binding_is_required(source):
    workdir, url, container = source
    names = []
    def inspect(name):
        names.append(name)
        return container
    assert runner.owned_source(workdir, url, inspect) == ("owned-container-id", "postgres")
    assert names == ["supabase_db_tallig123"]


@pytest.mark.parametrize("url", [
    "postgresql://postgres:local@remote.example:55001/postgres",
    "postgresql://postgres:local@127.0.0.1:55002/postgres",
    "postgresql://postgres:local@127.0.0.1:55001/existing_template",
    "postgresql://postgres:local@127.0.0.1:55001/postgres?hostaddr=203.0.113.1",
    "postgresql://other:local@127.0.0.1:55001/postgres",
])
def test_source_mismatch_fails_before_docker(source, url):
    workdir, _, _ = source
    def unexpected(_):
        pytest.fail("Invalid source reached Docker")
    with pytest.raises(ValueError, match="owned local source"):
        runner.owned_source(workdir, url, unexpected)


@pytest.mark.parametrize("change", ["stopped", "wrong_name", "wrong_port"])
def test_container_mismatch_cannot_authorize_clone(source, change):
    workdir, url, container = source
    if change == "stopped":
        container["State"]["Running"] = False
    elif change == "wrong_name":
        container["Name"] = "/supabase_db_another"
    else:
        container["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"] = "55002"
    with pytest.raises(ValueError, match="container does not match"):
        runner.owned_source(workdir, url, lambda _: container)


@pytest.mark.parametrize("observed", ["1\n", "0\n"])
def test_live_source_session_must_be_visible_inside_exact_container(monkeypatch, observed):
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def execute(self, query):
            assert query == "select pg_backend_pid()"
            return self
        def fetchone(self): return (12345,)
    calls = []
    def connect(url, **kwargs):
        assert url == "explicit-local-url"
        calls.append(kwargs["application_name"])
        return Connection()
    def output(args, **kwargs):
        assert args[:3] == ["docker", "exec", "pinned-container"]
        assert "pid=12345" in args[-1]
        assert calls[0] in args[-1]
        return observed
    monkeypatch.setattr(runner.psycopg, "connect", connect)
    monkeypatch.setattr(runner.subprocess, "check_output", output)
    if observed.strip() == "1":
        runner.verify_source_session("explicit-local-url", "pinned-container")
    else:
        with pytest.raises(ValueError, match="not served by"):
            runner.verify_source_session("explicit-local-url", "pinned-container")


@pytest.mark.parametrize("failure", [None, "createdb", "pg_restore", "pytest", "memberships"])
def test_cleanup_is_bound_only_to_successfully_created_clone(source, monkeypatch, failure):
    workdir, url, container = source
    monkeypatch.setenv("TALLI_SUPABASE_WORKDIR", str(workdir))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(runner, "inspect_container", lambda _: container)
    monkeypatch.setattr(runner, "verify_source_session", lambda *_: None)
    membership_reads = iter([[(1, 2, 2, False, False, True)],
                             [(1, 2, 2, failure == "memberships", False, True)]])
    monkeypatch.setattr(runner, "role_memberships", lambda *_: next(membership_reads))
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        command = args[4] if args[0] == "docker" else "pytest"
        if command == failure and failure != "pytest":
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 1 if failure == "pytest" else 0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    if failure in ("createdb", "pg_restore"):
        with pytest.raises(subprocess.CalledProcessError):
            runner.main()
    elif failure == "memberships":
        with pytest.raises(RuntimeError, match="changed cluster role memberships"):
            runner.main()
    else:
        assert runner.main() == (1 if failure == "pytest" else 0)
    create = next(args for args, _ in calls if "createdb" in args)
    clone = create[-1]
    assert clone.startswith("rf193_governance_") and len(clone) == len("rf193_governance_") + 32
    drops = [args for args, _ in calls if "dropdb" in args]
    assert drops == ([] if failure == "createdb" else [["docker", "exec", "-i", "owned-container-id", "dropdb", "-U", "supabase_admin", "--force", clone]])
    for args, kwargs in calls:
        if args[0] == "docker":
            assert args[3] == "owned-container-id"
        elif failure not in ("createdb", "pg_restore"):
            assert runner.conninfo_to_dict(kwargs["env"]["DATABASE_URL"])["dbname"] == clone
