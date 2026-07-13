from __future__ import annotations

import json
import subprocess
import sys
import unittest
from io import BytesIO
from pathlib import Path

from pydantic import ValidationError
from pypdf import PdfReader

from holding_core.corporate_documents import DividendDocumentInput, generate_owner_dividend_documents


ROOT = Path(__file__).resolve().parents[1]


def valid_input() -> DividendDocumentInput:
    return DividendDocumentInput.model_validate(
        {
            "company_name": "LOGISK ØDE TIGER AS",
            "org_number": "310279617",
            "income_year": 2025,
            "decision_date": "2025-06-01",
            "payment_date": "2025-06-15",
            "total_amount": 1000,
            "distributable_equity": 5000,
            "liquidity_after_payment": 1000,
            "allocations": [
                {
                    "shareholder_id": "owner-1",
                    "shareholder_name": "Viktig Rosin",
                    "share_count": 100,
                    "amount": 1000,
                }
            ],
        }
    )


class CorporateDocumentTest(unittest.TestCase):
    def test_generates_two_readable_unsigned_pdf_drafts(self) -> None:
        documents = generate_owner_dividend_documents(valid_input())

        self.assertEqual(
            [document.kind for document in documents],
            ["board_proposal", "general_meeting_minutes"],
        )
        self.assertEqual(
            [document.file_name for document in documents],
            ["styreforslag-og-protokoll-utbytte.pdf", "generalforsamlingsprotokoll-utbytte.pdf"],
        )
        for document in documents:
            with self.subTest(document=document.kind):
                self.assertEqual(document.content_type, "application/pdf")
                self.assertTrue(document.content.startswith(b"%PDF-"))
                self.assertLess(len(document.content), 100_000)
                reader = PdfReader(BytesIO(document.content))
                self.assertGreaterEqual(len(reader.pages), 1)
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                self.assertIn("UTKAST - MÅ KONTROLLERES OG SIGNERES", text)
                self.assertIn("LOGISK ØDE TIGER AS", text)
                self.assertIn("310 279 617", text)
                self.assertIn("kr 1 000,00", text)
                self.assertIn("Viktig Rosin", text)

        board_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(documents[0].content)).pages
        )
        meeting_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(documents[1].content)).pages
        )
        self.assertIn("forsvarlig egenkapital og likviditet", board_text)
        self.assertIn("Stemmer for", meeting_text)
        self.assertIn("Signaturer", meeting_text)

    def test_output_is_deterministic_for_same_input(self) -> None:
        first = generate_owner_dividend_documents(valid_input())
        second = generate_owner_dividend_documents(valid_input())
        self.assertEqual([document.content for document in first], [document.content for document in second])

    def test_rejects_invalid_org_number_and_allocation_total(self) -> None:
        payload = valid_input().model_dump(mode="json")
        payload["org_number"] = "123"
        with self.assertRaises(ValidationError):
            DividendDocumentInput.model_validate(payload)

        payload = valid_input().model_dump(mode="json")
        payload["payment_date"] = "2025-05-31"
        with self.assertRaises(ValidationError):
            DividendDocumentInput.model_validate(payload)

        payload = valid_input().model_dump(mode="json")
        payload["total_amount"] = "1200"
        payload["allocations"] = [
            {
                "shareholder_id": "owner-1",
                "shareholder_name": "Viktig Rosin",
                "share_count": 75,
                "amount": 800,
            },
            {
                "shareholder_id": "owner-2",
                "shareholder_name": "Rolig Rosin",
                "share_count": 25,
                "amount": 400,
            },
        ]
        with self.assertRaises(ValidationError):
            DividendDocumentInput.model_validate(payload)

        payload = valid_input().model_dump(mode="json")
        payload["allocations"][0]["amount"] = "999"
        with self.assertRaises(ValidationError):
            DividendDocumentInput.model_validate(payload)

    def test_cli_returns_base64_artifacts_without_writing_files(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "holding_cli.main",
                "generate-owner-dividend-documents",
                "--stdin-json",
            ],
            cwd=ROOT,
            input=valid_input().model_dump_json(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(len(output["documents"]), 2)
        self.assertTrue(all(document["content_type"] == "application/pdf" for document in output["documents"]))
        self.assertTrue(all(document["base64"].startswith("JVBER") for document in output["documents"]))


if __name__ == "__main__":
    unittest.main()
