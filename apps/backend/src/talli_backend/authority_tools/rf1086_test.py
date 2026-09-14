"""RF test command with durable write intent and exclusive local evidence ownership."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import math
import os
import subprocess
import shutil
import sys
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from talli_backend.adapters.rf1086_authority import Rf1086AuthorityAdapter
from talli_backend.authority_tools._grant import CliGrantConfiguration, request_token, required
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086AuthorityCall, Rf1086AuthorityError, assess_rf1086_readiness,
    generate_rf1086_documents, parse_rf1086_case, rf1086_xml_schema,
)

RF1086_SCOPE = "skatteetaten:innrapporteringaksjonaerregisteroppgave"


def _reject_json_constant(_value: str) -> None:
    raise ValueError("Invalid JSON constant.")


def _sha256(value: str) -> str:
    # Buffer.from(string, "utf8") replaces unpaired UTF-16 surrogates with U+FFFD.
    encoded = _utf16(value).decode("utf-16-be", errors="replace").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utf16(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _object_items(value: dict):
    # JavaScript enumerates canonical array-index keys before other string keys.
    indices = [key for key in value if isinstance(key, str) and key.isascii() and key.isdecimal()
               and str(int(key)) == key and int(key) < 2**32 - 1]
    return [(key, value[key]) for key in sorted(indices, key=int)] + [
        (key, item) for key, item in value.items() if key not in indices]


def _json_value(value):
    if isinstance(value, float):
        return None if not math.isfinite(value) else int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in _object_items(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            serialized = json.dumps(_json_value(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
            # JSON.stringify emits escapes for lone surrogates, preserving them
            # through a valid UTF-8 evidence file instead of changing the receipt.
            output.write(serialized.encode("utf-8", errors="backslashreplace"))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_evidence(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Atomic evidence replacement changes its inode; keep the sidecar forever.
    lock_path = path.with_name(f".{path.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Rf1086AuthorityError("RF1086_REHEARSAL_IN_PROGRESS") from None
        os.fchmod(descriptor, 0o600)
        yield
    finally:
        os.close(descriptor)


def _checkpoint(path: Path, evidence: dict, **updates) -> None:
    # Keep the last durable pending marker in memory if saving a response fails.
    updated = evidence | updates
    _write_json(path, updated)
    evidence.update(updates)


def _pending_write(path: Path, evidence: dict, name: str, body_hash: str, key: str) -> None:
    _checkpoint(path, evidence, status="pending_mutation", pendingOperation={
        "name": name, "bodyHash": body_hash, "idempotencyKey": key})


def _validate_saved_intent(prior: dict, shareholders: dict) -> None:
    try:
        keys = prior["idempotencyKeys"]
        values = [keys["hovedskjema"], keys["bekreft"], *keys["underskjema"].values()]
        valid_keys = (set(keys["underskjema"]) == set(shareholders)
                      and all(isinstance(key, str) and str(UUID(key)) == key for key in values)
                      and len(set(values)) == len(values))
    except (KeyError, TypeError, ValueError, AttributeError):
        valid_keys = False
    if not valid_keys:
        raise Rf1086AuthorityError("RF1086_SAVED_INTENT_INVALID")
    if prior.get("schemaVersion") not in {1, 2} or (prior.get("schemaVersion") == 2
                                                    and "pendingOperation" not in prior):
        raise Rf1086AuthorityError("RF1086_SAVED_INTENT_INVALID")
    if prior.get("pendingOperation") is not None or prior.get("status") in {
            "pending_mutation", "unknown"}:
        raise Rf1086AuthorityError("RF1086_RECONCILIATION_REQUIRED")
    confirmed = bool(prior.get("confirmation"))
    # Legacy journals did not checkpoint before POST: any unfinished write may
    # have reached the authority. Confirmed journals may only recover via GET.
    if not confirmed and (prior.get("schemaVersion") != 2 or prior.get("status") not in {
            "prepared", "hovedskjema_accepted", "underskjema_accepted"}):
        raise Rf1086AuthorityError("RF1086_RECONCILIATION_REQUIRED")
    if confirmed and (not prior.get("hovedskjema")
                      or set(prior.get("underskjema", {})) != set(shareholders)):
        raise Rf1086AuthorityError("RF1086_SAVED_INTENT_INVALID")
    try:
        base = f"https://api-test.sits.no/api/aksjonaerregister/v1/{prior['incomeYear']}"
        main = prior.get("hovedskjema")
        children = prior.get("underskjema", {})
        if not isinstance(children, dict) or not set(children) <= set(shareholders):
            raise ValueError()
        if children and not main:
            raise ValueError()
        if main:
            if str(UUID(main["hovedskjemaId"])) != main["hovedskjemaId"]:
                raise ValueError()
            _validate_saved_call(main["call"], keys["hovedskjema"], prior["payloadHashes"]["hovedskjema"], f"{base}/1086H")
        for identifier, child in children.items():
            _validate_saved_call(child["call"], keys["underskjema"][identifier],
                                 prior["payloadHashes"]["underskjema"][identifier], f"{base}/{main['hovedskjemaId']}/1086U")
        if confirmed:
            confirmation = prior["confirmation"]
            for name in ("dialogId", "forsendelseId"):
                if str(UUID(confirmation[name])) != confirmation[name]:
                    raise ValueError()
            if not isinstance(confirmation["oppgavegiversLeveranseReferanse"], str) or not confirmation["oppgavegiversLeveranseReferanse"]:
                raise ValueError()
            _validate_saved_call(confirmation["call"], keys["bekreft"], _sha256(""),
                                 f"{base}/{main['hovedskjemaId']}/bekreft?antall_underskjema={len(shareholders)}")
        if prior["status"] in {"hovedskjema_accepted", "underskjema_accepted"} and not main:
            raise ValueError()
        if prior["status"] in {"confirmed", "accepted"} and not confirmed:
            raise ValueError()
        if prior["status"] == "accepted":
            archive = prior["archive"]
            hashes = archive["documentHashes"]
            if (archive["lookupReferenceType"] != "forsendelseId"
                    or archive["lookupReferenceId"] != prior["confirmation"]["forsendelseId"]
                    or not isinstance(hashes, list) or not hashes
                    or type(archive["totalItems"]) is not int or archive["totalItems"] != len(hashes)
                    or any(not isinstance(digest, str) or len(digest) != 64
                           or any(character not in "0123456789abcdef" for character in digest) for digest in hashes)):
                raise ValueError()
            call = archive["call"]
            expected = (f"https://api-test.sits.no/api/aksjonaerregister/v1/{prior['incomeYear']}/forsendelser/"
                        f"{prior['confirmation']['forsendelseId']}/dokumenter?page=0&size=50")
            if (call["method"] != "GET" or call["endpoint"] != expected or call["bodyHash"] != _sha256("")
                    or call["idempotencyKey"] is not None or call["status"] != "accepted"):
                raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Rf1086AuthorityError("RF1086_SAVED_INTENT_INVALID") from None


def _validate_saved_call(call: dict, key: str, body_hash: str, endpoint: str) -> None:
    if (call["method"] != "POST" or call["endpoint"] != endpoint or call["idempotencyKey"] != key
            or call["bodyHash"] != body_hash or call["status"] != "accepted"):
        raise ValueError()


def _generate_xml(raw_case: object, output: Path) -> None:
    case = parse_rf1086_case(raw_case)
    if not assess_rf1086_readiness(case).is_ready:
        raise ValueError("Local RF-1086 command failed (simulate-aksjonaerregister).")
    documents = generate_rf1086_documents(case)
    (output / "1086H.xml").write_text(documents.hovedskjema_xml, encoding="utf-8")
    for shareholder_id, xml in documents.underskjema_xml.items():
        (output / f"1086U-{shareholder_id}.xml").write_text(xml, encoding="utf-8")


def _run_xml_command(arguments: list[str], environment: Mapping[str, str], *, remaining: int = 8 * 1024 * 1024) -> int:
    # Validation remains a fixed local xmllint operation. No credential or
    # application loader reaches the subprocess; combined diagnostics remain
    # bounded across the original main-then-children validation loop.
    child_environment = {name: value for name, value in environment.items()
                         if name in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
    with subprocess.Popen(arguments, env=child_environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0) as process:
        try:
            while chunk := process.stdout.read(min(65_536, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError("Local RF-1086 command failed (validate-rf1086-xml).")
            if process.wait():
                raise ValueError("Local RF-1086 command failed (validate-rf1086-xml).")
            return remaining
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def _validate_xml(main_path: Path, under_paths: list[Path], environment: Mapping[str, str]) -> None:
    binary = shutil.which("xmllint", path=environment.get("PATH", ""))
    if not binary:
        raise ValueError("Local RF-1086 command failed (validate-rf1086-xml).")
    with tempfile.TemporaryDirectory(prefix="talli-rf1086-schemas-") as directory:
        schemas = {}
        for name in ("hovedskjema", "underskjema"):
            path = Path(directory) / f"{name}.xsd"
            path.write_bytes(rf1086_xml_schema(name))
            schemas[name] = path
        remaining = 8 * 1024 * 1024
        for name, xml_path in [("hovedskjema", main_path), *(("underskjema", path) for path in under_paths)]:
            remaining = _run_xml_command([binary, "--noout", "--schema", str(schemas[name]), str(xml_path)],
                                         environment, remaining=remaining)


def _shareholder_write_order(identifiers: list[str], environment: Mapping[str, str]) -> list[str]:
    expression = ("let input='';process.stdin.setEncoding('utf8');"
        "process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>"
        "process.stdout.write(JSON.stringify(JSON.parse(input).sort((a,b)=>a.localeCompare(b)))));")
    child_environment = {name: value for name, value in environment.items()
                         if name in {"PATH", "LANG", "LC_ALL", "LC_COLLATE", "LC_CTYPE", "LANGUAGE", "SYSTEMROOT"}}
    result = subprocess.run(["node", "-e", expression], input=json.dumps(identifiers),
                            env=child_environment, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode or len(result.stdout.encode()) > 8 * 1024 * 1024:
        raise ValueError("Local RF-1086 shareholder ordering failed.")
    ordered = json.loads(result.stdout, parse_constant=_reject_json_constant)
    if not isinstance(ordered, list) or sorted(ordered, key=_utf16) != sorted(identifiers, key=_utf16):
        raise ValueError("Local RF-1086 shareholder ordering is invalid.")
    return ordered


def _call(call: Rf1086AuthorityCall) -> dict:
    return {"method": call.method, "endpoint": call.endpoint, "bodyHash": call.body_hash,
            "idempotencyKey": call.idempotency_key, "status": call.status}


def _summary(evidence: dict) -> dict:
    output = {"ok": True, "status": evidence["status"], "environment": evidence["environment"],
              "companyOrgNumber": evidence["companyOrgNumber"], "incomeYear": evidence["incomeYear"],
              "evidencePath": evidence["evidencePath"]}
    for target, source, name in (
        ("hovedskjemaId", "hovedskjema", "hovedskjemaId"),
        ("receiptReference", "confirmation", "oppgavegiversLeveranseReferanse"),
        ("dialogId", "confirmation", "dialogId"), ("archiveReference", "confirmation", "forsendelseId"),
        ("archivedDocumentCount", "archive", "totalItems"),
    ):
        if evidence.get(source) is not None and name in evidence[source]:
            output[target] = evidence[source][name]
    return _json_value(output)


def _error(error: Exception) -> dict:
    if isinstance(error, Rf1086AuthorityError):
        return {"code": error.code, "status": error.status, "correlationId": error.correlation_id,
                "retryable": error.retryable, "message": str(error)}
    return {"code": "RF1086_LOCAL_OR_RESPONSE_ERROR", "status": None, "correlationId": None,
            "retryable": False, "message": "RF-1086 local command or response is invalid."}


async def run(environment: Mapping[str, str] | None = None, *, token_transport=None,
              authority_transport=None, sleep=asyncio.sleep) -> dict:
    values = os.environ if environment is None else environment
    if required(values, "TALLI_RF1086_APPROVED_TEST_WRITE") != "true":
        raise ValueError("TALLI_RF1086_APPROVED_TEST_WRITE must be exactly true for an authority test write.")
    if required(values, "TALLI_MASKINPORTEN_ENVIRONMENT") != "test":
        raise ValueError("The RF-1086 authority test command refuses every environment except test.")
    scope = required(values, "TALLI_MASKINPORTEN_SCOPE")
    if scope != RF1086_SCOPE:
        raise ValueError("The RF-1086 authority test requires its exact RF-1086 scope.")
    evidence_path = Path(required(values, "TALLI_RF1086_EVIDENCE_PATH")).resolve()
    with _exclusive_evidence(evidence_path):
        return await _run_owned(values, scope, evidence_path, token_transport=token_transport,
                                authority_transport=authority_transport, sleep=sleep)


def _prepare_xml(case: dict, evidence_path: Path, values: Mapping[str, str]):
    # Never read or overwrite another journal's retained payload while preparing.
    with tempfile.TemporaryDirectory(prefix=f".{evidence_path.name}.prepare-", dir=evidence_path.parent) as temporary:
        output_directory = Path(temporary)
        _generate_xml(case, output_directory)
        main_path = output_directory / "1086H.xml"
        under_paths = sorted((path for path in output_directory.iterdir()
                             if path.name.startswith("1086U-") and path.name.endswith(".xml")),
                             key=lambda path: _utf16(path.name))
        if not under_paths:
            raise ValueError("Generated RF-1086 payload has no underskjema.")
        _validate_xml(main_path, under_paths, values)
        # read_bytes avoids Python newline translation of the exact statutory XML.
        main_xml = main_path.read_bytes().decode("utf-8")
        under_xml = {path.name[len("1086U-"):-len(".xml")]: path.read_bytes().decode("utf-8") for path in under_paths}
    return main_xml, dict(_object_items(under_xml))


def _retain_xml(evidence_path: Path, main_xml: str, under_xml: dict) -> None:
    directory = evidence_path.with_name(f".{evidence_path.name}.xml")
    if directory.is_symlink():
        raise ValueError("RF-1086 XML output must not be a symlink.")
    directory.mkdir(mode=0o700, exist_ok=True)
    documents = {"1086H.xml": main_xml, **{f"1086U-{key}.xml": value for key, value in under_xml.items()}}
    for name, xml in documents.items():
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(xml.encode("utf-8"))
    for old in directory.glob("1086*.xml"):
        if old.name not in documents:
            old.unlink()


async def _run_owned(values, scope, evidence_path, *, token_transport, authority_transport, sleep):
    case_path = Path(required(values, "TALLI_RF1086_CASE_PATH")).resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    company = case.get("company") or {}
    company_org_number = str(company.get("org_number", ""))
    raw_year = company.get("income_year")
    try:
        numeric_year = float(raw_year)
        if not numeric_year.is_integer():
            raise ValueError()
        income_year = int(numeric_year)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("RF-1086 case income year is invalid.") from None
    if company_org_number != required(values, "TALLI_MASKINPORTEN_SYSTEM_USER_ORG"):
        raise ValueError("RF-1086 case organization must equal the Maskinporten system-user organization.")
    events = case.get("events") if isinstance(case.get("events"), list) else []
    if any(not isinstance(event, dict) or event.get("type") != "formation" for event in events):
        raise ValueError("RF-1086 authority rehearsal is limited to no-activity or formation cases.")
    main_xml, under_xml = _prepare_xml(case, evidence_path, values)
    payload_hashes = {"hovedskjema": _sha256(main_xml),
                      "underskjema": {key: _sha256(xml) for key, xml in under_xml.items()}}
    try:
        prior = json.loads(evidence_path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except FileNotFoundError:
        prior = None
    if prior is not None and (prior.get("environment") != "test"
            or prior.get("companyOrgNumber") != company_org_number or prior.get("incomeYear") != income_year
            or prior.get("payloadHashes", {}).get("hovedskjema") != payload_hashes["hovedskjema"]
            or _object_items(prior.get("payloadHashes", {}).get("underskjema", {})) != _object_items(payload_hashes["underskjema"])):
        raise ValueError("Existing RF-1086 evidence belongs to a different payload; choose a new evidence path.")
    if prior is not None:
        _validate_saved_intent(prior, under_xml)
    if prior is not None and prior.get("status") == "accepted":
        return _summary(prior)
    _retain_xml(evidence_path, main_xml, under_xml)
    prior = prior or {}
    keys = prior.get("idempotencyKeys")
    if keys is None:
        keys = {"hovedskjema": str(uuid4()),
            "underskjema": {key: str(uuid4()) for key in sorted(under_xml, key=_utf16)}, "bekreft": str(uuid4())}
    evidence = {"schemaVersion": 2, "status": "prepared", "environment": "test",
        "authority": "Skatteetaten RF-1086 API", "companyOrgNumber": company_org_number,
        "companyName": str(company.get("name", "")), "incomeYear": income_year, "scope": scope,
        "evidencePath": str(evidence_path), "preparedAt": _now() if prior.get("preparedAt") is None else prior["preparedAt"],
        "payloadHashes": payload_hashes, "idempotencyKeys": keys,
        "hovedskjema": prior.get("hovedskjema"), "underskjema": prior.get("underskjema") or {},
        "confirmation": prior.get("confirmation"), "archive": prior.get("archive"),
        "pendingOperation": None, "error": None}
    _write_json(evidence_path, evidence)
    token = await request_token(CliGrantConfiguration.from_environment(values), transport=token_transport)
    try:
        client = Rf1086AuthorityAdapter(token, environment="test", transport=authority_transport)
        if not evidence["hovedskjema"]:
            _pending_write(evidence_path, evidence, "hovedskjema", payload_hashes["hovedskjema"], keys["hovedskjema"])
            result = await client.post_hovedskjema(income_year=income_year, xml=main_xml, idempotency_key=keys["hovedskjema"])
            _checkpoint(evidence_path, evidence, pendingOperation=None, status="hovedskjema_accepted",
                        hovedskjema={"hovedskjemaId": result.hovedskjema_id, "call": _call(result.call)})
        for shareholder_id in _shareholder_write_order(list(under_xml), values):
            xml = under_xml[shareholder_id]
            if evidence["underskjema"].get(shareholder_id):
                continue
            _pending_write(evidence_path, evidence, f"underskjema:{shareholder_id}",
                           payload_hashes["underskjema"][shareholder_id], keys["underskjema"][shareholder_id])
            result = await client.post_underskjema(income_year=income_year,
                hovedskjema_id=evidence["hovedskjema"]["hovedskjemaId"], xml=xml,
                idempotency_key=keys["underskjema"][shareholder_id])
            _checkpoint(evidence_path, evidence, pendingOperation=None, status="underskjema_accepted",
                        underskjema=evidence["underskjema"] | {shareholder_id: {"call": _call(result.call)}})
        if not evidence["confirmation"]:
            _pending_write(evidence_path, evidence, "bekreft", _sha256(""), keys["bekreft"])
            result = await client.confirm(income_year=income_year,
                hovedskjema_id=evidence["hovedskjema"]["hovedskjemaId"], underskjema_count=len(under_xml),
                idempotency_key=keys["bekreft"])
            _checkpoint(evidence_path, evidence, pendingOperation=None, status="confirmed", confirmation={
                "oppgavegiversLeveranseReferanse": result.oppgavegivers_leveranse_referanse,
                "dialogId": result.dialog_id, "forsendelseId": result.forsendelse_id, "call": _call(result.call)})
        archive = None
        for attempt in range(1, 6):
            try:
                result = await client.list_documents(income_year=income_year,
                    reference_id=evidence["confirmation"]["forsendelseId"], page=0, size=50)
                if result.total_items > 0 and result.documents:
                    # The old harness hashes embedded entries only. A document
                    # reference remains a blocked response, with no extra GET.
                    archive = {"lookupReferenceType": "forsendelseId",
                        "lookupReferenceId": evidence["confirmation"]["forsendelseId"],
                        "totalItems": result.total_items, "totalPages": result.total_pages,
                        "currentPage": result.current_page,
                        "documentHashes": [_sha256(document) for document in result.documents],
                        "call": _call(result.call)}
                    break
            except Rf1086AuthorityError as error:
                eventual_archive = (error.status == 404 and error.code == "GLD_021"
                                    and "GLD_1017" in error.specification_codes)
                if not eventual_archive or attempt == 5:
                    raise
            if attempt < 5:
                await sleep(2)
        if archive is None:
            raise ValueError("RF-1086 archive returned no documents after confirmation.")
        evidence.update(archive=archive, status="accepted", acceptedAt=_now())
        _write_json(evidence_path, evidence)
        return _summary(evidence)
    except Exception as error:
        evidence["status"] = ("unknown" if evidence["pendingOperation"] else
                              "failed_retryable" if isinstance(error, Rf1086AuthorityError) and error.retryable else "failed_blocked")
        evidence["error"] = _error(error)
        _write_json(evidence_path, evidence)
        raise
    finally:
        token.discard()


def main() -> int:
    os.umask(0o077)
    try:
        print(json.dumps(asyncio.run(run()), separators=(",", ":")))
        return 0
    except Rf1086AuthorityError as error:
        output = {"ok": False, **_error(error)}
    except Exception:
        output = {"ok": False, "code": "local_configuration_or_payload_error", "status": None,
                  "message": "RF-1086 local configuration or payload is invalid."}
    print(json.dumps(output, separators=(",", ":")), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
