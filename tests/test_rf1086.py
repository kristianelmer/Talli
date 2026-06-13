from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from holding_core.models import FilingCase
from holding_core.rf1086 import filing_preview, generate_rf1086, readiness_report, write_rf1086
from holding_core.rf1086_codes import (
    ACQUISITION_PURCHASE_CODE,
    DISPOSAL_SALE_CODE,
    DIVIDEND_DISTRIBUTION_CODE,
    FORMATION_STIFTELSE_CODE,
    production_code_blockers,
    rf1086_code_decisions,
)
from holding_core.validation import run_rf1086_validation


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "rf1086"
INVALID_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "rf1086_invalid"
HOVED_XSD = ROOT / "docs" / "filing" / "aksjonaerregisteroppgaveHovedskjema.xsd"
UNDER_XSD = ROOT / "docs" / "filing" / "aksjonaerregisteroppgaveUnderskjema.xsd"


class Rf1086SimulationTest(unittest.TestCase):
    def test_fixture_cases_generate_xml(self) -> None:
        for fixture in sorted(FIXTURE_DIR.glob("*.json")):
            with self.subTest(fixture=fixture.name):
                case = FilingCase.from_json_file(fixture)
                documents = generate_rf1086(case)

                self.assertIn("<Skjema", documents.hovedskjema_xml)
                self.assertIn('blankettnummer="RF-1086"', documents.hovedskjema_xml)
                self.assertEqual(len(documents.underskjema_xml), len(case.shareholders))
                for xml in documents.underskjema_xml.values():
                    self.assertIn('blankettnummer="RF-1086-U"', xml)

                report = readiness_report(case)
                self.assertIn("Status: klar for simulering", report)

                preview = filing_preview(case)
                self.assertIn(case.company.name, preview)

    def test_generated_xml_validates_against_official_xsd(self) -> None:
        xmllint = shutil.which("xmllint")
        if not xmllint:
            self.skipTest("xmllint is not installed")

        for fixture in sorted(FIXTURE_DIR.glob("*.json")):
            with self.subTest(fixture=fixture.name):
                case = FilingCase.from_json_file(fixture)
                with tempfile.TemporaryDirectory() as temp_dir:
                    paths = write_rf1086(case, temp_dir)
                    hoved = next(path for path in paths if path.name == "1086H.xml")
                    unders = [path for path in paths if path.name.startswith("1086U-")]

                    self._assert_xsd_valid(xmllint, HOVED_XSD, hoved)
                    for under in unders:
                        self._assert_xsd_valid(xmllint, UNDER_XSD, under)

    def test_cli_generates_and_validates(self) -> None:
        xmllint = shutil.which("xmllint")
        if not xmllint:
            self.skipTest("xmllint is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = FIXTURE_DIR / "stiftelse.json"
            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "holding_cli.main",
                    "simulate-aksjonaerregister",
                    "--case",
                    str(fixture),
                    "--out",
                    temp_dir,
                    "--preview",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Generated", result.stdout)
            self.assertIn("Aksjonærregisteroppgaven", result.stdout)

            unders = sorted(str(path) for path in Path(temp_dir).glob("1086U-*.xml"))
            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "holding_cli.main",
                    "validate-rf1086-xml",
                    "--hovedskjema",
                    str(Path(temp_dir) / "1086H.xml"),
                    "--underskjema",
                    *unders,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_validate_case_json(self) -> None:
        fixture = FIXTURE_DIR / "dividend.json"
        result = subprocess.run(
            [
                "python3",
                "-m",
                "holding_cli.main",
                "validate-case",
                "--case",
                str(fixture),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["filing"], "aksjonærregisteroppgaven")
        self.assertEqual(payload["status"], "ready")

    def test_cli_invalid_case_fails_cleanly(self) -> None:
        fixture = INVALID_FIXTURE_DIR / "mismatched_share_count.json"
        result = subprocess.run(
            [
                "python3",
                "-m",
                "holding_cli.main",
                "simulate-aksjonaerregister",
                "--case",
                str(fixture),
                "--out",
                "out/should-not-exist",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Case validation failed", result.stderr)
        self.assertNotIn("Generated", result.stdout)

    def test_cli_unsupported_case_blocks_before_xml(self) -> None:
        fixture = INVALID_FIXTURE_DIR / "unsupported_share_class.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "holding_cli.main",
                    "simulate-aksjonaerregister",
                    "--case",
                    str(fixture),
                    "--out",
                    temp_dir,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Status: blokkert", result.stdout)
            self.assertIn("Kun ordinær aksjeklasse", result.stdout)
            self.assertEqual(list(Path(temp_dir).glob("*.xml")), [])

    def test_public_data_validation_report_classifies_pass_and_blocked_cases(self) -> None:
        report = run_rf1086_validation(
            [
                FIXTURE_DIR / "no_activity.json",
                INVALID_FIXTURE_DIR / "unsupported_share_class.json",
                INVALID_FIXTURE_DIR / "mismatched_share_count.json",
            ]
        )

        outcomes = {case.case_id or Path(case.case_path).name: case.outcome for case in report.cases}
        self.assertEqual(outcomes["no_activity"], "pass")
        self.assertEqual(outcomes["unsupported_share_class"], "blocked")
        self.assertEqual(outcomes["mismatched_share_count.json"], "blocked")
        self.assertIn("Public and synthetic data cannot prove voucher completeness.", report.limitations)

    def test_cli_public_data_validation_json(self) -> None:
        result = subprocess.run(
            [
                "python3",
                "-m",
                "holding_cli.main",
                "validate-public-data",
                "--case",
                str(FIXTURE_DIR / "no_activity.json"),
                "--case",
                str(INVALID_FIXTURE_DIR / "unsupported_share_class.json"),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["filing"], "aksjonærregisteroppgaven")
        self.assertEqual([case["outcome"] for case in payload["cases"]], ["pass", "blocked"])

    def test_formation_allocations_are_per_shareholder(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse_two_founders.json")
        documents = generate_rf1086(case)

        founder_a_xml = documents.underskjema_xml["founder_a"]
        founder_b_xml = documents.underskjema_xml["founder_b"]

        self.assertIn("<AksjerKjopAntall-datadef-12153 orid=\"12153\">60</AksjerKjopAntall-datadef-12153>", founder_a_xml)
        self.assertIn("<AksjeAnskaffelsesverdi-datadef-17636 orid=\"17636\">18000</AksjeAnskaffelsesverdi-datadef-17636>", founder_a_xml)
        self.assertIn("<AksjerKjopAntall-datadef-12153 orid=\"12153\">40</AksjerKjopAntall-datadef-12153>", founder_b_xml)
        self.assertIn("<AksjeAnskaffelsesverdi-datadef-17636 orid=\"17636\">12000</AksjeAnskaffelsesverdi-datadef-17636>", founder_b_xml)

    def test_transaction_code_registry_marks_public_label_only_values_as_production_blockers(self) -> None:
        decisions = {decision.event: decision for decision in rf1086_code_decisions()}
        blockers = {decision.event for decision in production_code_blockers()}

        self.assertEqual(decisions["stiftelse"].code_value, FORMATION_STIFTELSE_CODE)
        self.assertFalse(decisions["stiftelse"].production_blocker)
        self.assertEqual(decisions["kjop"].code_value, ACQUISITION_PURCHASE_CODE)
        self.assertEqual(decisions["salg"].code_value, DISPOSAL_SALE_CODE)
        self.assertEqual(decisions["utbytte"].code_value, DIVIDEND_DISTRIBUTION_CODE)
        self.assertEqual(blockers, {"kjop", "salg", "utbytte"})

    def test_generated_xml_uses_central_transaction_code_registry(self) -> None:
        sale_case = FilingCase.from_json_file(FIXTURE_DIR / "share_sale.json")
        sale_documents = generate_rf1086(sale_case)
        joined_sale_xml = "\n".join(sale_documents.underskjema_xml.values())

        self.assertIn(f">{ACQUISITION_PURCHASE_CODE}</AksjeErvervType-datadef-17745>", joined_sale_xml)
        self.assertIn(f">{DISPOSAL_SALE_CODE}</AksjerArvMvOmsattType-datadef-17753>", joined_sale_xml)

        dividend_case = FilingCase.from_json_file(FIXTURE_DIR / "dividend.json")
        dividend_documents = generate_rf1086(dividend_case)

        self.assertIn(
            f">{DIVIDEND_DISTRIBUTION_CODE}</AksjeUtbytteHendelsestype-datadef-36564>",
            dividend_documents.hovedskjema_xml,
        )

    def _assert_xsd_valid(self, xmllint: str, schema: Path, xml: Path) -> None:
        result = subprocess.run(
            [xmllint, "--noout", "--schema", str(schema), str(xml)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
