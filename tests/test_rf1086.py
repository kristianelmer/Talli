from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from holding_core.models import FilingCase
from holding_core.rf1086 import filing_preview, generate_rf1086, readiness_report, write_rf1086


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

    def test_formation_allocations_are_per_shareholder(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse_two_founders.json")
        documents = generate_rf1086(case)

        founder_a_xml = documents.underskjema_xml["founder_a"]
        founder_b_xml = documents.underskjema_xml["founder_b"]

        self.assertIn("<AksjerKjopAntall-datadef-12153 orid=\"12153\">60</AksjerKjopAntall-datadef-12153>", founder_a_xml)
        self.assertIn("<AksjeAnskaffelsesverdi-datadef-17636 orid=\"17636\">18000</AksjeAnskaffelsesverdi-datadef-17636>", founder_a_xml)
        self.assertIn("<AksjerKjopAntall-datadef-12153 orid=\"12153\">40</AksjerKjopAntall-datadef-12153>", founder_b_xml)
        self.assertIn("<AksjeAnskaffelsesverdi-datadef-17636 orid=\"17636\">12000</AksjeAnskaffelsesverdi-datadef-17636>", founder_b_xml)

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
