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
from holding_core.rf1086 import filing_preview, write_rf1086


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

    args = parser.parse_args(argv)
    if args.command == "simulate-aksjonaerregister":
        return _simulate(args.case, args.out, args.preview)
    if args.command == "validate-rf1086-xml":
        return _validate(args.hovedskjema, args.underskjema)
    if args.command == "validate-case":
        return _validate_case(args.case, args.json)
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


def _load_case(case_path: str) -> FilingCase | None:
    try:
        return FilingCase.from_json_file(case_path)
    except (OSError, ValueError, ValidationError) as error:
        print(f"Case validation failed: {error}", file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
