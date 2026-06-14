from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from holding_core.models import FilingCase
from holding_core.readiness import assess_rf1086_readiness, format_readiness_report
from holding_core.rf1086 import filing_preview, generate_rf1086, write_rf1086
from holding_core.submission import confirm_authority, confirm_preview, mark_submitted, prepare_submission, register_api_call, store_receipt
from holding_core.validation import run_annual_compliance_validation, run_rf1086_validation


ROOT = Path(__file__).resolve().parents[1]
HOVED_XSD = ROOT / "docs" / "filing" / "aksjonaerregisteroppgaveHovedskjema.xsd"
UNDER_XSD = ROOT / "docs" / "filing" / "aksjonaerregisteroppgaveUnderskjema.xsd"


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
    return 2


def _simulate(case_path: str, out_dir: str, should_preview: bool) -> int:
    case = _load_case(case_path)
    if case is None:
        return 1

    readiness = assess_rf1086_readiness(case)
    if not readiness.is_ready:
        print(format_readiness_report(readiness), end="")
        return 1

    paths = write_rf1086(case, out_dir)
    print(f"Generated {len(paths)} files in {out_dir}")
    print(format_readiness_report(readiness), end="")
    if should_preview:
        print()
        print(filing_preview(case), end="")
    return 0


def _validate(hovedskjema: str, underskjema: list[str]) -> int:
    xmllint = shutil.which("xmllint")
    if not xmllint:
        print("xmllint is required for XSD validation but was not found.", file=sys.stderr)
        return 2

    checks = [(HOVED_XSD, Path(hovedskjema)), *[(UNDER_XSD, Path(path)) for path in underskjema]]
    for schema, xml_path in checks:
        result = subprocess.run(
            [xmllint, "--noout", "--schema", str(schema), str(xml_path)],
            text=True,
            capture_output=True,
            check=False,
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
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(format_readiness_report(result), end="")
    return 0 if result.is_ready else 1


def _validate_public_data(case_paths: list[str], as_json: bool) -> int:
    report = run_rf1086_validation(case_paths)
    if as_json:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
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
        case = FilingCase.model_validate_json(sys.stdin.read())
    except (ValueError, ValidationError) as error:
        print(json.dumps({"status": "blocked", "issues": [{"code": "invalid_case", "message": str(error)}]}))
        return 1

    readiness = assess_rf1086_readiness(case)
    payload: dict[str, object] = {
        "filing": readiness.filing,
        "status": readiness.status,
        "issues": [issue.model_dump() for issue in readiness.issues],
        "preview": filing_preview(case),
    }
    if readiness.is_ready:
        documents = generate_rf1086(case)
        payload["hovedskjemaXml"] = documents.hovedskjema_xml
        payload["underskjemaXml"] = documents.underskjema_xml
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if readiness.is_ready else 1


def _simulate_rf1086_submission() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not payload.get("authority_confirmed"):
            raise ValueError("authority confirmation is required before simulated submission")
        if not payload.get("preview_confirmed"):
            raise ValueError("final preview confirmation is required before simulated submission")
        underskjema_xml = payload.get("underskjema_xml") or {}
        if not isinstance(underskjema_xml, dict):
            raise ValueError("underskjema_xml must be an object")

        submission = prepare_submission(
            filing=str(payload["filing"]),
            company_id=str(payload["company_id"]),
            income_year=int(payload["income_year"]),
        )
        submission = confirm_authority(submission, user_id=str(payload["user_id"]))
        submission = confirm_preview(submission, user_id=str(payload["user_id"]))

        preview_id = str(payload["preview_id"])
        base_endpoint = f"/api/aksjonaerregister/v1/{submission.income_year}"
        hovedskjema_id = f"simulated-{preview_id}"
        submission = register_api_call(
            submission,
            endpoint=f"{base_endpoint}/1086H",
            body={"content_type": "application/xml", "xml": str(payload["hovedskjema_xml"])},
        )
        for shareholder_id, xml in sorted(underskjema_xml.items()):
            submission = register_api_call(
                submission,
                endpoint=f"{base_endpoint}/{hovedskjema_id}/1086U/{shareholder_id}",
                body={"content_type": "application/xml", "xml": str(xml)},
            )
        submission = register_api_call(
            submission,
            endpoint=f"{base_endpoint}/{hovedskjema_id}/bekreft",
            body={"antall_underskjema": len(underskjema_xml)},
        )
        submission = register_api_call(
            submission,
            endpoint=f"{base_endpoint}/{hovedskjema_id}/dokumenter",
            body={"page": 1, "max_forms": 50},
        )
        receipt_id = f"sim-rf1086-{submission.company_id}-{submission.income_year}-{preview_id[:8]}"
        submission = store_receipt(
            mark_submitted(submission, feedback_document_ids=(f"sim-feedback-{preview_id[:8]}",)),
            receipt_id=receipt_id,
        )
        print(submission.model_dump_json())
        return 0
    except (KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "failed_blocked",
                    "failure_code": "simulation_input_blocked",
                    "failure_message": str(error),
                }
            )
        )
        return 1


def _load_case(case_path: str) -> FilingCase | None:
    try:
        return FilingCase.from_json_file(case_path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Case validation failed: {error}", file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
