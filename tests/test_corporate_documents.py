from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from holding_core.corporate_documents import (
    CorporateArtifactKind,
    CorporateDecisionInput,
    CorporateDocumentValidationError,
    canonical_decision_json,
    decision_sha256,
    required_artifact_kinds,
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


if __name__ == "__main__":
    unittest.main()
