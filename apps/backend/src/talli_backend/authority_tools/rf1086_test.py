"""Frozen RF authority test command, relocated under the exact #150 amendment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from talli_backend.adapters.rf1086_authority import Rf1086AuthorityAdapter
from talli_backend.authority_tools._grant import CliGrantConfiguration, request_token, required
from talli_backend.compatibility.rf1086_authority_workflow import Rf1086AuthorityCall, Rf1086AuthorityError

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
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_python(arguments: list[str], environment: Mapping[str, str]) -> None:
    configured = environment.get("TALLI_PYTHON_BIN", "").strip()
    candidates = (Path.cwd() / ".venv/bin/python", Path.cwd() / ".venv/Scripts/python.exe")
    binary = configured or next((str(path) for path in candidates if path.exists()), sys.executable)
    # Statutory generation is unchanged; the subprocess receives no credentials.
    child_environment = {name: value for name, value in environment.items()
                         if name in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
    with subprocess.Popen([binary, "-m", "holding_cli.main", *arguments], cwd=Path.cwd(),
            env=child_environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0) as process:
        try:
            remaining = 8 * 1024 * 1024
            while chunk := process.stdout.read(min(65_536, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError(f"Local RF-1086 command failed ({arguments[0]}).")
            if process.wait():
                raise ValueError(f"Local RF-1086 command failed ({arguments[0]}).")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


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
    case_path = Path(required(values, "TALLI_RF1086_CASE_PATH")).resolve()
    evidence_path = Path(required(values, "TALLI_RF1086_EVIDENCE_PATH")).resolve()
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
    output_directory = evidence_path.parent / "xml"
    output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    _run_python(["simulate-aksjonaerregister", "--case", str(case_path), "--out", str(output_directory)], values)
    main_path = output_directory / "1086H.xml"
    under_paths = sorted((path for path in output_directory.iterdir()
                         if path.name.startswith("1086U-") and path.name.endswith(".xml")),
                         key=lambda path: _utf16(path.name))
    if not under_paths:
        raise ValueError("Generated RF-1086 payload has no underskjema.")
    _run_python(["validate-rf1086-xml", "--hovedskjema", str(main_path), "--underskjema",
                 *(str(path) for path in under_paths)], values)
    # read_bytes avoids Python newline translation of the exact statutory XML.
    main_xml = main_path.read_bytes().decode("utf-8")
    under_xml = {path.name[len("1086U-"):-len(".xml")]: path.read_bytes().decode("utf-8") for path in under_paths}
    under_xml = dict(_object_items(under_xml))
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
    if prior is not None and prior.get("status") == "accepted":
        return _summary(prior)
    prior = prior or {}
    keys = prior.get("idempotencyKeys")
    if keys is None:
        keys = {"hovedskjema": str(uuid4()),
            "underskjema": {key: str(uuid4()) for key in sorted(under_xml, key=_utf16)}, "bekreft": str(uuid4())}
    evidence = {"schemaVersion": 1, "status": "prepared", "environment": "test",
        "authority": "Skatteetaten RF-1086 API", "companyOrgNumber": company_org_number,
        "companyName": str(company.get("name", "")), "incomeYear": income_year, "scope": scope,
        "evidencePath": str(evidence_path), "preparedAt": _now() if prior.get("preparedAt") is None else prior["preparedAt"],
        "payloadHashes": payload_hashes, "idempotencyKeys": keys,
        "hovedskjema": prior.get("hovedskjema"), "underskjema": prior.get("underskjema") or {},
        "confirmation": prior.get("confirmation"), "archive": prior.get("archive"), "error": None}
    _write_json(evidence_path, evidence)
    token = await request_token(CliGrantConfiguration.from_environment(values), transport=token_transport)
    try:
        client = Rf1086AuthorityAdapter(token, environment="test", transport=authority_transport)
        if not evidence["hovedskjema"]:
            result = await client.post_hovedskjema(income_year=income_year, xml=main_xml, idempotency_key=keys["hovedskjema"])
            evidence["hovedskjema"] = {"hovedskjemaId": result.hovedskjema_id, "call": _call(result.call)}
            evidence["status"] = "hovedskjema_accepted"
            _write_json(evidence_path, evidence)
        for shareholder_id in _shareholder_write_order(list(under_xml), values):
            xml = under_xml[shareholder_id]
            if evidence["underskjema"].get(shareholder_id):
                continue
            result = await client.post_underskjema(income_year=income_year,
                hovedskjema_id=evidence["hovedskjema"]["hovedskjemaId"], xml=xml,
                idempotency_key=keys["underskjema"][shareholder_id])
            evidence["underskjema"][shareholder_id] = {"call": _call(result.call)}
            evidence["status"] = "underskjema_accepted"
            _write_json(evidence_path, evidence)
        if not evidence["confirmation"]:
            result = await client.confirm(income_year=income_year,
                hovedskjema_id=evidence["hovedskjema"]["hovedskjemaId"], underskjema_count=len(under_xml),
                idempotency_key=keys["bekreft"])
            evidence["confirmation"] = {"oppgavegiversLeveranseReferanse": result.oppgavegivers_leveranse_referanse,
                "dialogId": result.dialog_id, "forsendelseId": result.forsendelse_id, "call": _call(result.call)}
            evidence["status"] = "confirmed"
            _write_json(evidence_path, evidence)
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
        evidence["status"] = "failed_retryable" if isinstance(error, Rf1086AuthorityError) and error.retryable else "failed_blocked"
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
