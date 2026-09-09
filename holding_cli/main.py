from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from holding_core.corporate_documents import (
    CorporateDecisionInput,
    CorporateDocumentValidationError,
    render_corporate_documents,
)
from holding_core.validation import run_annual_compliance_validation
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086Case, Rf1086ValidationInput, parse_rf1086_case,
    assess_rf1086_readiness, format_rf1086_readiness_report as format_readiness_report,
    generate_rf1086_documents as generate_rf1086, render_rf1086_preview,
    validate_rf1086_cases, rf1086_xml_schema,
    parse_rf1086_offline_simulation_input, simulate_rf1086_offline_submission,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="talli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate = subparsers.add_parser("simulate-aksjonaerregister", help="Generate RF-1086 simulation XML")
    simulate.add_argument("--case", required=True, help="Path to JSON filing case")
    simulate.add_argument("--out", default="out/rf1086", help="Output directory")
    simulate.add_argument("--preview", action="store_true", help="Print Norwegian filing preview")

    validate = subparsers.add_parser("validate-rf1086-xml", help="Validate generated XML with official XSD files")
    validate.add_argument("--hovedskjema", required=True)
    validate.add_argument("--underskjema", nargs="+", required=True)

    validate_case = subparsers.add_parser("validate-case", help="Validate a filing case against launch readiness rules")
    validate_case.add_argument("--case", required=True, help="Path to JSON filing case")
    validate_case.add_argument("--json", action="store_true", help="Print machine-readable readiness JSON")

    validate_public = subparsers.add_parser(
        "validate-public-data",
        help="Run public/synthetic validation cases through the RF-1086 simulation harness",
    )
    validate_public.add_argument("--case", action="append", required=True, help="Path to JSON filing case")
    validate_public.add_argument("--json", action="store_true", help="Print machine-readable validation report")

    validate_annual_public = subparsers.add_parser(
        "validate-annual-public-data",
        help="Run public/synthetic annual accounts and company tax return validation cases",
    )
    validate_annual_public.add_argument("--case", action="append", required=True, help="Path to annual validation fixture")
    validate_annual_public.add_argument("--json", action="store_true", help="Print machine-readable validation report")

    render_rf1086 = subparsers.add_parser(
        "render-rf1086-preview",
        help="Render RF-1086 readiness, preview, and XML from JSON case on stdin",
    )
    render_rf1086.add_argument("--stdin-json", action="store_true", required=True)

    simulate_rf1086_submission = subparsers.add_parser(
        "simulate-rf1086-submission",
        help="Prepare confirmed simulated RF-1086 submission and receipt from preview JSON on stdin",
    )
    simulate_rf1086_submission.add_argument("--stdin-json", action="store_true", required=True)

    render_corporate = subparsers.add_parser(
        "render-corporate-documents",
        help="Render deterministic corporate decision PDFs from JSON on stdin",
    )
    render_corporate.add_argument("--stdin-json", action="store_true", required=True)

    args = parser.parse_args(argv)
    if args.command == "simulate-aksjonaerregister":
        return _simulate(args.case, args.out, args.preview)
    if args.command == "validate-rf1086-xml":
        return _validate(args.hovedskjema, args.underskjema)
    if args.command == "validate-case":
        return _validate_case(args.case, args.json)
    if args.command == "validate-public-data":
        return _validate_public_data(args.case, args.json)
    if args.command == "validate-annual-public-data":
        return _validate_annual_public_data(args.case, args.json)
    if args.command == "render-rf1086-preview":
        return _render_rf1086_preview()
    if args.command == "simulate-rf1086-submission":
        return _simulate_rf1086_submission()
    if args.command == "render-corporate-documents":
        return _render_corporate_documents()
    return 2


def _simulate(case_path: str, out_dir: str, should_preview: bool) -> int:
    case = _load_case(case_path)
    if case is None:
        return 1

    readiness = assess_rf1086_readiness(case)
    if not readiness.is_ready:
        print(format_readiness_report(readiness), end="")
        return 1

    paths = _write_rf1086(case, out_dir)
    print(f"Generated {len(paths)} files in {out_dir}")
    print(format_readiness_report(readiness), end="")
    if should_preview:
        print()
        print(render_rf1086_preview(case).preview, end="")
    return 0


def _validate(hovedskjema: str, underskjema: list[str]) -> int:
    xmllint = shutil.which("xmllint")
    if not xmllint:
        print("xmllint is required for XSD validation but was not found.", file=sys.stderr)
        return 2
    with TemporaryDirectory(prefix="talli-rf1086-xsd-") as directory:
        hoved_xsd = Path(directory) / "aksjonaerregisteroppgaveHovedskjema.xsd"
        under_xsd = Path(directory) / "aksjonaerregisteroppgaveUnderskjema.xsd"
        hoved_xsd.write_bytes(rf1086_xml_schema("hovedskjema"))
        under_xsd.write_bytes(rf1086_xml_schema("underskjema"))
        checks = [(hoved_xsd, Path(hovedskjema)), *[(under_xsd, Path(path)) for path in underskjema]]
        for schema, xml_path in checks:
            result = subprocess.run(
                [xmllint, "--noout", "--schema", str(schema), str(xml_path)],
                text=True, capture_output=True, check=False,
            )
            if result.returncode != 0:
                print(result.stdout, end="")
                print(result.stderr, end="", file=sys.stderr)
                return result.returncode
            print(result.stderr.strip())
    return 0


def _validate_case(case_path: str, as_json: bool) -> int:
    case = _load_case(case_path)
    if case is None:
        return 1

    result = assess_rf1086_readiness(case)
    if as_json:
        print(json.dumps(_rf_json_values(result), ensure_ascii=False, indent=2))
    else:
        print(format_readiness_report(result), end="")
    return 0 if result.is_ready else 1


def _validate_public_data(case_paths: list[str], as_json: bool) -> int:
    report = validate_rf1086_cases(tuple(_rf_validation_input(path) for path in case_paths))
    if as_json:
        print(json.dumps(_rf_json_values(report), ensure_ascii=False, indent=2))
    else:
        print(f"Validation report: {report.filing}")
        print(f"Source: {report.source}")
        print()
        print("Limitations:")
        for limitation in report.limitations:
            print(f"- {limitation}")
        print()
        print("Cases:")
        for case in report.cases:
            name = case.case_id or case.case_path
            print(f"- {name}: {case.outcome} ({case.generated_documents} document(s))")
            for issue in case.issues:
                print(f"  - {issue}")
    return 1 if any(case.outcome == "blocked" for case in report.cases) else 0


def _validate_annual_public_data(case_paths: list[str], as_json: bool) -> int:
    report = run_annual_compliance_validation(case_paths)
    if as_json:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(f"Validation report: {report.filing}")
        print(f"Source: {report.source}")
        print()
        print("Authority maps:")
        for path in report.authority_maps:
            print(f"- {path}")
        print()
        print("Limitations:")
        for limitation in report.limitations:
            print(f"- {limitation}")
        print()
        print("Cases:")
        for case in report.cases:
            name = case.case_id or case.case_path
            print(f"- {name}: {case.outcome} ({case.generated_previews} preview(s))")
            for issue in case.issues + case.mismatches:
                print(f"  - {issue}")
    return 1 if any(case.outcome in {"blocked", "unsupported", "mismatch"} for case in report.cases) else 0


def _render_rf1086_preview() -> int:
    try:
        case = parse_rf1086_case(sys.stdin.read())
    except (ValueError, ValidationError) as error:
        print(json.dumps({"status": "blocked", "issues": [{"code": "invalid_case", "message": str(error)}]}))
        return 1

    readiness = assess_rf1086_readiness(case)
    payload: dict[str, object] = {
        "filing": readiness.filing,
        "status": readiness.status,
        "issues": [_rf_json_values(issue) for issue in readiness.issues],
        "preview": render_rf1086_preview(case).preview,
    }
    if readiness.is_ready:
        documents = generate_rf1086(case)
        payload["hovedskjemaXml"] = documents.hovedskjema_xml
        payload["underskjemaXml"] = dict(documents.underskjema_xml)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if readiness.is_ready else 1


def _simulate_rf1086_submission() -> int:
    try:
        request = parse_rf1086_offline_simulation_input(json.loads(sys.stdin.read()))
        result = simulate_rf1086_offline_submission(request)
        print(json.dumps(_rf_json_values(result), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (KeyError, TypeError, ValueError) as error:
        print(json.dumps({
            "status": "failed_blocked",
            "failure_code": "simulation_input_blocked",
            "failure_message": str(error),
        }))
        return 1


def _render_corporate_documents() -> int:
    try:
        decision = CorporateDecisionInput.model_validate_json(sys.stdin.read())
        artifacts = render_corporate_documents(decision)
        print(
            json.dumps(
                {
                    "status": "rendered",
                    "decisionHash": artifacts[0].decision_hash,
                    "artifacts": [
                        {
                            "artifactKind": artifact.artifact_kind.value,
                            "filename": artifact.filename,
                            "templateVersion": artifact.template_version,
                            "decisionHash": artifact.decision_hash,
                            "contentSha256": artifact.content_sha256,
                            "byteLength": artifact.byte_length,
                            "pdfBase64": base64.b64encode(artifact.pdf_bytes).decode("ascii"),
                        }
                        for artifact in artifacts
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    except ValidationError as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "issues": [
                        {
                            "code": "corporate_documents_invalid_input",
                            "message": "Dokumentgrunnlaget er ugyldig.",
                            "details": error.error_count(),
                        }
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1
    except CorporateDocumentValidationError as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "issues": [{"code": error.code, "message": str(error)}],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "issues": [
                        {
                            "code": "corporate_documents_render_failed",
                            "message": "Dokumentene kunne ikke genereres.",
                        }
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1


def _rf_json_values(value):
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if is_dataclass(value):
        return {item.name: _rf_json_values(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {key: _rf_json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rf_json_values(item) for item in value]
    return value


def _write_rf1086(case: Rf1086Case, out_dir: str) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    documents = generate_rf1086(case)
    paths = [out / "1086H.xml"]
    paths[0].write_text(documents.hovedskjema_xml, encoding="utf-8")
    for shareholder_id, xml in documents.underskjema_xml.items():
        path = out / f"1086U-{shareholder_id}.xml"
        path.write_text(xml, encoding="utf-8")
        paths.append(path)
    return paths


def _rf_validation_input(case_path: str) -> Rf1086ValidationInput:
    try:
        return Rf1086ValidationInput(case_path, Path(case_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return Rf1086ValidationInput(case_path, None, str(error))


def _load_case(case_path: str) -> Rf1086Case | None:
    try:
        return parse_rf1086_case(Path(case_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as error:
        print(f"Case validation failed: {error}", file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
