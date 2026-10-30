"""Bounded generated column-ACL compatibility check in the pinned RF image.

This deliberately cannot identify the statement in a failed production replay.
It only checks what PostgreSQL 17.6 emits for a disposable fixture and how the
old prefix boundary and current unmodeled-table parser handle that emission.
"""

import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import rf1086_restore_control as control
import rf1086_restore_metadata as metadata
from rf1086_actual_replay_package import IMAGE


MAX_ARCHIVE = 2 * 1024 * 1024
MAX_SCRIPT = 2 * 1024 * 1024
ROLE = "talli_focused_reader"
TABLE = "talli_focused_acl"


def check():
    started = time.monotonic()
    run = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    job = os.environ["GITHUB_JOB"]
    if (not re.fullmatch(r"[1-9][0-9]{0,19}", run)
            or not re.fullmatch(r"[1-9][0-9]{0,5}", attempt)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", job)):
        raise ValueError("run_binding")
    workdir = Path(os.environ["TALLI_FOCUSED_WORKDIR"]).resolve(strict=True)
    if not workdir.name.startswith("talli-supabase-local."):
        raise ValueError("workdir_binding")
    config = (workdir / "supabase" / "config.toml").read_text()
    project = re.search(r'^project_id = "(tallig[0-9]+)"$', config, re.M)
    if project is None:
        raise ValueError("project_binding")
    container = "supabase_db_" + project.group(1)
    image = subprocess.run(
        ["docker", "inspect", "--format", "{{.Image}}", container],
        capture_output=True, timeout=8, check=True,
    ).stdout.strip().decode("ascii")
    if image != IMAGE:
        raise ValueError("image_binding")
    budget = control.RecoveryBudget(time.monotonic())
    end = min(budget.end - 70, time.monotonic() + 120)

    def command(args, *, data=None, cap=4096):
        return budget.command(["docker", "exec", "-u", "postgres", "-i", container, *args],
                              data=data, cap=cap, end=end)

    server = command(["psql", "-X", "-At", "-U", "postgres", "-d", "postgres", "-c", "SHOW server_version"])
    dump_version = command(["pg_dump", "--version"])
    if not re.fullmatch(rb"17\.6(?: \([^\r\n]{1,128}\))?\s*", server):
        raise ValueError("server_version")
    if not re.fullmatch(rb"pg_dump \(PostgreSQL\) 17\.6\s*", dump_version):
        raise ValueError("dump_version")
    # This isolated Supabase database is destroyed by the workflow cleanup.
    fixture = (f"CREATE ROLE {ROLE};\n"
               f"CREATE TABLE public.{TABLE} (id integer);\n"
               f"GRANT SELECT(id) ON TABLE public.{TABLE} TO {ROLE};\n").encode("ascii")
    command(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-q", "-U", "postgres", "-d", "postgres"],
            data=fixture)
    archive = command(["pg_dump", "-U", "postgres", "-d", "postgres", "-Fc",
                       "--table=public." + TABLE], cap=MAX_ARCHIVE)
    script = command(["pg_restore", "--file=-"], data=archive, cap=MAX_SCRIPT)
    candidates = re.findall(rb"(?m)^GRANT[^\r\n]{1,512};$", script)
    expected = re.compile(rb"GRANT SELECT\s*\(id\) ON TABLE public\." + TABLE.encode() +
                          rb" TO " + ROLE.encode() + rb";")
    matching = [line for line in candidates if expected.fullmatch(line)]
    if len(matching) != 1:
        raise ValueError("generated_acl_shape")
    statement = matching[0]
    test_path = Path(__file__).resolve().parents[1] / "apps" / "backend" / "tests"
    sys.path.insert(0, str(test_path))
    import test_rf1086_restore_metadata as fixtures  # generated fixture only

    parse_budget = metadata.Budget(fixtures.end())
    parsed = next(metadata._statements(statement + b"\n", parse_budget))
    old = metadata._statement_copy(parsed, parse_budget)
    try:
        metadata._operation_prefix(old, metadata.DOMAINS["r"])
    except metadata.ledger.Unavailable as error:
        if type(error) is not metadata.ledger.Unavailable or error.reason != "role":
            raise ValueError("old_boundary") from None
    else:
        raise ValueError("old_boundary")
    source_object = dataclasses.replace(fixtures.source().objects[0],
                                        identity=("relation", "public", TABLE),
                                        owner="postgres", columns=1)
    result = metadata._target_candidates(
        parsed, {("relation", b"public", TABLE.encode()): (source_object,)},
        parse_budget, roles={ROLE, "postgres"},
    )
    if not result.unmodeled or result.exact is not source_object:
        raise ValueError("new_boundary")
    candidate = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                               timeout=5, check=True).stdout.strip().decode("ascii")
    if candidate != os.environ["GITHUB_SHA"]:
        raise ValueError("candidate_binding")
    root = Path(__file__).resolve().parents[1]
    sources = {}
    for relative in ("scripts/rf1086_focused_image_check.py",
                     "scripts/rf1086_restore_metadata.py",
                     "scripts/rf1086_restore_control.py"):
        sources[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    return {
        "schema": "rf1086-focused-image-check-v1",
        "candidate": candidate, "run": run, "attempt": attempt, "job": job,
        "sources": sources,
        "image": IMAGE,
        "serverVersion": "17.6",
        "archive": {"bytes": len(archive), "sha256": hashlib.sha256(archive).hexdigest()},
        "script": {"bytes": len(script), "sha256": hashlib.sha256(script).hexdigest()},
        "statementSha256": hashlib.sha256(statement).hexdigest(),
        "oldPrefix": "role_unavailable", "newUnmodeled": "accepted",
        "scope": "generated_image_emission_and_unmodeled_parser_only",
        "prepareArchiveExercised": False,
        "originalFailureStatementKnown": False,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(check(), sort_keys=True))
    except Exception as error:
        # No subprocess stderr, SQL, or role/catalog details leave the runner.
        allowed = {"run_binding", "workdir_binding", "project_binding", "image_binding",
                   "server_version", "dump_version", "generated_acl_shape", "old_boundary",
                   "new_boundary", "candidate_binding"}
        reason = str(error) if type(error) is ValueError and str(error) in allowed else "focused_check_unavailable"
        category = "parser_boundary_failure" if reason in {"old_boundary", "new_boundary"} else "fixture_or_binding_failure"
        print(json.dumps({"schema": "rf1086-focused-image-check-v1",
                          "status": "unavailable", "category": category,
                          "reason": reason}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
