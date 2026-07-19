from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from holding_core.corporate_documents import (
    CorporateArtifactKind,
    CorporateDecisionInput,
    CorporateDocumentValidationError,
    RenderedCorporateArtifact,
    canonical_decision_json,
    decision_sha256,
    required_artifact_kinds,
    render_corporate_documents,
    validate_supported_scope,
)


FIXTURES = Path(__file__).parent / "fixtures" / "corporate_documents"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CorporateDecisionModelTests(unittest.TestCase):
    def test_canonical_json_and_hash_are_stable(self) -> None:
        payload = load_fixture("owner_dividend.json")
        reordered = {key: payload[key] for key in reversed(tuple(payload))}

        decision = CorporateDecisionInput.model_validate(payload)
        reordered_decision = CorporateDecisionInput.model_validate(reordered)

        self.assertEqual(canonical_decision_json(decision), canonical_decision_json(reordered_decision))
        self.assertEqual(
            decision_sha256(decision),
            "011d1f6df34bf979ee043f7466236aea727198b8b7606968ecf0fc761107366b",
        )
        self.assertIn("LOGISK ØDE TIGER AS".encode(), canonical_decision_json(decision))
        self.assertNotIn(b"generated_at", canonical_decision_json(decision))

    def test_required_artifacts_follow_decision_kind(self) -> None:
        owner = CorporateDecisionInput.model_validate(load_fixture("owner_dividend.json"))
        annual = CorporateDecisionInput.model_validate(load_fixture("annual_close.json"))

        self.assertEqual(
            required_artifact_kinds(owner),
            (
                CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
                CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
            ),
        )
        self.assertEqual(
            required_artifact_kinds(annual),
            (
                CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
                CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,
            ),
        )

    def test_supported_owner_dividend_and_annual_close_validate(self) -> None:
        for fixture in ("owner_dividend.json", "annual_close.json"):
            decision = CorporateDecisionInput.model_validate(load_fixture(fixture))
            validate_supported_scope(decision)

    def test_unsupported_cases_have_machine_readable_codes(self) -> None:
        cases: tuple[tuple[str, callable], ...] = (
            (
                "corporate_documents_unsupported_dividend_basis",
                lambda value: value["confirmations"].__setitem__("supported_dividend_basis", False),
            ),
            (
                "corporate_documents_incomplete_board",
                lambda value: value["confirmations"].__setitem__("full_board_participation", False),
            ),
            (
                "corporate_documents_incomplete_share_representation",
                lambda value: value["shareholders"][1].__setitem__("represented_share_count", 399),
            ),
            (
                "corporate_documents_non_unanimous",
                lambda value: value["shareholders"][1].__setitem__("vote", "against"),
            ),
            (
                "corporate_documents_allocation_mismatch",
                lambda value: value["dividend"]["allocations"][1].__setitem__("amount_ore", 3999999),
            ),
            (
                "corporate_documents_equity_or_liquidity_failed",
                lambda value: value["financial_totals"].__setitem__("available_distribution_ore", 9999999),
            ),
        )

        base = load_fixture("owner_dividend.json")
        for expected_code, mutate in cases:
            with self.subTest(expected_code=expected_code):
                payload = deepcopy(base)
                mutate(payload)
                decision = CorporateDecisionInput.model_validate(payload)
                with self.assertRaises(CorporateDocumentValidationError) as raised:
                    validate_supported_scope(decision)
                self.assertEqual(raised.exception.code, expected_code)

    def test_dividend_payment_must_follow_decision(self) -> None:
        payload = load_fixture("owner_dividend.json")
        payload["dividend"]["payment_date"] = "2025-06-19"
        decision = CorporateDecisionInput.model_validate(payload)

        with self.assertRaises(CorporateDocumentValidationError) as raised:
            validate_supported_scope(decision)

        self.assertEqual(raised.exception.code, "corporate_documents_unsupported_dividend_basis")


class CorporateDocumentRenderingTests(unittest.TestCase):
    def test_render_is_byte_identical_and_hash_bound(self) -> None:
        decision = CorporateDecisionInput.model_validate(load_fixture("owner_dividend.json"))

        first = render_corporate_documents(decision)
        second = render_corporate_documents(decision)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        for artifact in first:
            self.assertIsInstance(artifact, RenderedCorporateArtifact)
            self.assertTrue(artifact.pdf_bytes.startswith(b"%PDF-"))
            self.assertEqual(artifact.byte_length, len(artifact.pdf_bytes))
            self.assertEqual(artifact.decision_hash, decision_sha256(decision))
            self.assertEqual(artifact.content_sha256, hashlib.sha256(artifact.pdf_bytes).hexdigest())
            self.assertTrue(artifact.filename.endswith(".pdf"))

    def test_all_four_artifacts_extract_reviewed_norwegian_facts(self) -> None:
        pdftotext = shutil.which("pdftotext")
        self.assertIsNotNone(pdftotext, "Poppler pdftotext is required for PDF content verification")

        for fixture in ("owner_dividend.json", "annual_close.json"):
            decision = CorporateDecisionInput.model_validate(load_fixture(fixture))
            for artifact in render_corporate_documents(decision):
                with self.subTest(fixture=fixture, kind=artifact.artifact_kind):
                    with tempfile.TemporaryDirectory() as directory:
                        pdf_path = Path(directory) / artifact.filename
                        text_path = Path(directory) / "artifact.txt"
                        pdf_path.write_bytes(artifact.pdf_bytes)
                        result = subprocess.run(
                            [pdftotext, "-layout", str(pdf_path), str(text_path)],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        content = text_path.read_text(encoding="utf-8")
                    self.assertIn("LOGISK ØDE TIGER AS", content)
                    self.assertIn("310 279 617", content)
                    self.assertIn("Åse Nordmann", content)
                    self.assertIn("Jørgen Østby", content)
                    self.assertIn(decision_sha256(decision), content)
                    self.assertIn(decision.template_version, content)
                    self.assertIn("Signatur", content)

    def test_cli_returns_base64_artifacts_and_typed_block(self) -> None:
        success = subprocess.run(
            [sys.executable, "-m", "holding_cli.main", "render-corporate-documents", "--stdin-json"],
            input=json.dumps(load_fixture("owner_dividend.json"), ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        rendered = json.loads(success.stdout)
        self.assertEqual(rendered["status"], "rendered")
        self.assertEqual(len(rendered["artifacts"]), 2)
        self.assertGreater(len(rendered["artifacts"][0]["pdfBase64"]), 100)

        blocked = subprocess.run(
            [sys.executable, "-m", "holding_cli.main", "render-corporate-documents", "--stdin-json"],
            input="{}",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(blocked.returncode, 1)
        failure = json.loads(blocked.stdout)
        self.assertEqual(failure["status"], "blocked")
        self.assertEqual(failure["issues"][0]["code"], "corporate_documents_invalid_input")


if __name__ == "__main__":
    unittest.main()
