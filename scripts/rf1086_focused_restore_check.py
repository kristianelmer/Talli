"""Observe real identity construction on a fresh, pinned-image fixture.

The caller body is empty: completing this diagnostic never proves RF business
recovery, reproduces an older archive, or replaces the full release rehearsal.
"""
import time

ENTRY_STARTED = time.monotonic()

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tomllib

import rf1086_restore_control as control
import rf1086_identity_restore as identity
from rf1086_actual_replay_package import IMAGE


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "rf1086-focused-restore-check-v2"
FAILURE_SCHEMA = "rf1086-focused-post-construction-failure-v2"
CONSTRUCTION_PREFIX = "owned_identity_restore_construction "
CATALOG_PREFIX = "owned_identity_restore_catalog_diagnostic "
MAX_OUTPUT = 64 * 1024
SOURCE_PATHS = (
    "scripts/rf1086_focused_restore_check.py",
    "scripts/rf1086_identity_restore.py",
    "scripts/rf1086_restore_control.py",
    "scripts/rf1086_restore_metadata.py",
    "scripts/rf1086_catalog_difference.py",
    "scripts/rf1086_actual_replay_package.py",
    "scripts/test-corporate-reporting-owned-clone.py",
    "scripts/prepare-isolated-supabase-workdir.mjs",
    ".github/workflows/rf1086-focused-restore.yml",
)


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, "producer_output")
            value[key] = item
        return value

    def invalid(_):
        raise ValueError("producer_output")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class PrivateOutput:
    """Keep bounded producer text in memory; never echo unknown output."""
    def __init__(self):
        self.parts = []
        self.bytes = 0

    def write(self, value):
        need(type(value) is str, "producer_output")
        size = len(value.encode("utf-8"))
        need(self.bytes + size <= MAX_OUTPUT, "producer_output")
        self.bytes += size
        self.parts.append(value)
        return len(value)

    def flush(self):
        pass

    def records(self, prefix):
        result = []
        for line in "".join(self.parts).splitlines():
            if line.startswith(prefix):
                raw = line[len(prefix):].encode("utf-8")
                need(len(raw) <= 24 * 1024, "producer_output")
                value = strict_json(raw)
                need(control.ledger.canonical(value) == raw, "producer_output")
                result.append((value, hashlib.sha256(raw).hexdigest()))
        return result

    def clear(self):
        self.parts.clear()
        self.bytes = 0


@contextmanager
def local_environment(database_url, api_url, workdir):
    changes = {"DATABASE_URL": database_url, "SUPABASE_URL": api_url,
               "TALLI_SUPABASE_WORKDIR": str(workdir)}
    previous = {key: os.environ.get(key) for key in changes}
    os.environ.update(changes)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def source_bindings():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in SOURCE_PATHS}


def failure_details(error, budget):
    try:
        with control.io_deadline(budget, end=min(budget.end, time.monotonic() + 0.250)):
            endpoint = None
            if type(error) is control.EndpointAdmissionFailure:
                service, predicate = error.service, error.predicate
                if (type(service) is str and service in control.ENDPOINT_ADMISSION_SERVICES
                        and type(predicate) is str and predicate in control.ENDPOINT_ADMISSION_PREDICATES):
                    endpoint = {"service": service, "predicate": predicate}
            return {"location": control._diagnostic_location(error, budget),
                    "endpointAdmission": endpoint}
    except Exception:
        budget.context.raise_if_fatal()
        return {"location": None, "endpointAdmission": None}


def run_context(database_url, api_url, workdir, boundary, budget):
    private = PrivateOutput()
    entered = completed = False
    failure = None
    try:
        with local_environment(database_url, api_url, workdir):
            with redirect_stdout(private), redirect_stderr(private):
                try:
                    with identity.restored_identity(database_url, workdir, boundary, budget=budget):
                        entered = True
                        # Deliberately no filing, browser, or business assertions.
                    completed = True
                except Exception as error:
                    failure = error
        records = private.records(CONSTRUCTION_PREFIX)
        diagnostics = private.records(CATALOG_PREFIX)
        preparation = private.records(control.DIAGNOSTIC_PREFIX)
        need(len(records) == 1 and len(diagnostics) <= 1 and len(preparation) <= 1, "producer_output")
        receipt, receipt_hash = records[0]
        need(type(receipt) is dict and receipt.get("schema") == control.SCHEMA,
             "producer_output")
        need(set(receipt) == set("schema status reason configurationSha256 code bindings identities counts hooks mutations delivery observers fingerprints cleanupComplete identitySourcePostcheck businessComplete outerBusinessPostchecks phaseElapsedSeconds".split()), "producer_output")
        need(receipt["status"] in ("constructed", "unavailable")
             and (receipt["reason"] is None or receipt["reason"] in control.REASONS), "producer_output")
        need(type(receipt["cleanupComplete"]) is bool
             and type(receipt["identitySourcePostcheck"]) is bool, "producer_output")
        fingerprints = receipt["fingerprints"]
        need(type(fingerprints) is dict and set(fingerprints) == {"source", "target"},
             "producer_output")
        for value in fingerprints.values():
            need(value is None or (type(value) is dict
                 and set(value) == {"roles", "catalog", "auth", "companyMemberships"}
                 and all(type(x) is str and re.fullmatch("[a-f0-9]{64}", x)
                         for x in value.values())), "producer_output")
        clean = receipt["cleanupComplete"] and receipt["identitySourcePostcheck"]
        matching = fingerprints["source"] is not None and fingerprints["source"] == fingerprints["target"]
        catalog_mismatch = (fingerprints["source"] is not None
                            and fingerprints["target"] is not None
                            and fingerprints["source"]["catalog"] != fingerprints["target"]["catalog"])
        outcome = "unavailable"
        if completed and entered and failure is None and clean and matching and receipt["status"] == "constructed":
            outcome = "identity_context_completed"
        elif not entered and failure is not None and clean and catalog_mismatch and receipt["reason"] == "postcondition":
            outcome = "catalog_postcondition_rejected"
        diagnostic = diagnostics[0][0] if diagnostics else None
        # A closed producer schema and its exact construction commitment are
        # validated again by the manifest-bound, offline evidence reader.
        if diagnostic is not None:
            need(catalog_mismatch and type(diagnostic) is dict, "producer_output")
            control.validate_catalog_postcondition(
                diagnostic, construction_raw=control.ledger.canonical(receipt).decode("ascii"))
        pre_target = preparation[0][0] if preparation else None
        if pre_target is not None:
            control.validate_pre_target_diagnostic(pre_target)
        post_failure = None
        if (failure is not None and not entered and not completed and clean and matching
                and receipt["status"] == "constructed"):
            post_failure = {"schema": FAILURE_SCHEMA, "constructionSha256": receipt_hash,
                            **failure_details(failure, budget)}
        return {"identityOutcome": outcome, "identityContextEntered": entered,
                "identityContextCompleted": completed, "construction": receipt,
                "constructionReceiptSha256": receipt_hash,
                "catalogDiagnostic": diagnostic, "preTargetDiagnostic": pre_target,
                "postConstructionFailure": post_failure}
    finally:
        private.clear()


def check(started=ENTRY_STARTED):
    budget = control.RecoveryBudget(started)
    run, attempt, job = (os.environ[name] for name in
                         ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB"))
    need(re.fullmatch(r"[1-9][0-9]{0,19}", run)
         and re.fullmatch(r"[1-9][0-9]{0,5}", attempt)
         and job == "focused-restore", "run_binding")
    candidate = os.environ["GITHUB_SHA"]
    need(re.fullmatch(r"[a-f0-9]{40}", candidate), "candidate_binding")
    head = budget.command(["git", "rev-parse", "HEAD"], cap=4096,
                          end=min(budget.end, time.monotonic() + 5)).decode("ascii").strip()
    need(head == candidate, "candidate_binding")
    workdir = Path(os.environ["TALLI_FOCUSED_WORKDIR"]).resolve(strict=True)
    need(workdir.name.startswith("talli-supabase-local."), "workdir_binding")
    config = tomllib.loads((workdir / "supabase/config.toml").read_text())
    project = config["project_id"]
    need(type(project) is str and re.fullmatch(r"tallig[0-9]+", project), "workdir_binding")
    status = strict_json(budget.command(
        ["npm", "exec", "--", "supabase", "status", "--workdir", str(workdir), "--output", "json"],
        cap=64 * 1024, end=min(budget.end, time.monotonic() + 12)))
    need(type(status) is dict, "fixture_binding")
    database_url, api_url = status.get("DB_URL"), status.get("API_URL")
    need(all(type(v) is str and 0 < len(v) <= 4096 for v in (database_url, api_url)), "fixture_binding")
    del status
    container = "supabase_db_" + project
    actual_image = budget.command(["docker", "inspect", "--format", "{{.Image}}", container],
                                  cap=4096, end=min(budget.end, time.monotonic() + 8)).decode("ascii").strip()
    need(actual_image == IMAGE, "image_binding")
    server = budget.command(["docker", "exec", container, "psql", "-XAt", "-U", "postgres",
                             "-d", "postgres", "-c", "SHOW server_version"], cap=4096)
    dump = budget.command(["docker", "exec", container, "pg_dump", "--version"], cap=4096)
    need(re.fullmatch(rb"17\.6(?: \([^\r\n]{1,128}\))?\s*", server)
         and re.fullmatch(rb"pg_dump \(PostgreSQL\) 17\.6\s*", dump), "version_binding")
    spec = importlib.util.spec_from_file_location("focused_owned_boundary", ROOT / "scripts/test-corporate-reporting-owned-clone.py")
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    result = run_context(database_url, api_url, workdir, boundary, budget)
    budget.enter("output")
    with control.io_deadline(budget):
        diagnostic_complete = (result["identityOutcome"] == "identity_context_completed"
                               or (result["identityOutcome"] == "catalog_postcondition_rejected"
                                   and result["catalogDiagnostic"] is not None
                                   and result["catalogDiagnostic"]["status"] == "observed"))
        result.update(schema=SCHEMA, candidate=candidate, run=run, attempt=attempt, job=job,
                      image=IMAGE, serverVersion="17.6", sources=source_bindings(),
                      scope="generated_same_image_production_identity_context",
                      businessVerified=False, originalArchiveReplayed=False,
                      originalFailureCauseKnown=False,
                      diagnosticComplete=diagnostic_complete,
                      elapsedSeconds=round(time.monotonic() - started, 3))
        raw = control.ledger.canonical(result)
        need(len(raw) <= MAX_OUTPUT, "producer_output")
        print(raw.decode("ascii"), flush=True)
    return 0 if diagnostic_complete else 1


def main():
    try:
        return check()
    except (KeyboardInterrupt, SystemExit):
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "reason": "cancelled"}, sort_keys=True), file=sys.stderr)
        return 130
    except Exception as error:
        allowed = {"run_binding", "candidate_binding", "workdir_binding", "fixture_binding",
                   "image_binding", "version_binding", "producer_output"}
        reason = str(error) if type(error) is ValueError and str(error) in allowed else "focused_restore_unavailable"
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "reason": reason}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
