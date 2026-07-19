from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from holding_core.billing import assign_standard_pricing
from holding_core.models import FilingCase
from holding_core.rf1086_submission import (
    Rf1086SubmissionMode,
    prepare_rf1086_api_calls,
    prepare_rf1086_submission,
    store_rf1086_feedback_and_receipt,
)
from holding_core.security import StepUpContext
from holding_core.submission import (
    SubmissionStatus,
    confirm_authority,
    confirm_preview,
    mark_retryable_failure,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "rf1086"


class Rf1086ProductionSubmissionTest(unittest.TestCase):
    def test_submission_prep_requires_paid_billing_gate(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse.json")
        account = assign_standard_pricing(case.company.org_number)

        submission = prepare_rf1086_submission(case, account)

        self.assertEqual(submission.status, SubmissionStatus.FAILED_BLOCKED)
        self.assertEqual(submission.failure_code, "subscription_required")

    def test_excluded_transaction_events_block_production_prep(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "share_sale.json")
        account = assign_standard_pricing(case.company.org_number).model_copy(
            update={"subscription_active": True, "filing_package_paid": True}
        )

        submission = prepare_rf1086_submission(case, account)

        self.assertEqual(submission.status, SubmissionStatus.FAILED_BLOCKED)
        self.assertEqual(submission.failure_code, "RF1086_EVENT_UNSUPPORTED")
        self.assertIn("kjop=K", submission.failure_message or "")
        self.assertIn("salg=S", submission.failure_message or "")
        self.assertIn("bare åpnet for stiftelse/no-activity", submission.failure_message or "")
        self.assertIn("ekskludert fra live filing", submission.failure_message or "")

    def test_verified_stiftelse_code_passes_rf1086_code_gate(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse.json")
        account = assign_standard_pricing(case.company.org_number).model_copy(
            update={"subscription_active": True, "filing_package_paid": True}
        )

        submission = prepare_rf1086_submission(case, account)

        self.assertEqual(submission.status, SubmissionStatus.READY)
        self.assertIsNone(submission.failure_code)

    def test_test_mode_prepares_idempotent_rf1086_calls_after_authority_confirmations(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse.json")
        account = assign_standard_pricing(case.company.org_number).model_copy(
            update={"subscription_active": True, "filing_package_paid": True}
        )
        submission = prepare_rf1086_submission(case, account)

        with self.assertRaisesRegex(ValueError, "authority and final preview"):
            prepare_rf1086_api_calls(submission, case)

        confirmed = confirm_preview(confirm_authority(submission, user_id="owner"), user_id="owner")
        first = prepare_rf1086_api_calls(confirmed, case)
        second = prepare_rf1086_api_calls(first, case)

        self.assertEqual(first.status, SubmissionStatus.SUBMITTING)
        self.assertEqual(len(first.calls), 4)
        self.assertEqual(len(second.calls), 4)
        self.assertTrue(any(call.endpoint.endswith("/1086H") for call in first.calls))
        self.assertTrue(any(call.endpoint.endswith("/simulated-hovedskjema-id/1086U") for call in first.calls))
        self.assertTrue(
            any(call.endpoint.endswith("/simulated-hovedskjema-id/bekreft?antall_underskjema=1") for call in first.calls)
        )
        self.assertTrue(
            any(
                call.endpoint.endswith("/forsendelser/simulated-forsendelse-id/dokumenter?page=0&size=50")
                for call in first.calls
            )
        )

    def test_feedback_receipt_and_retryable_failures_are_recorded(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse.json")
        account = assign_standard_pricing(case.company.org_number).model_copy(
            update={"subscription_active": True, "filing_package_paid": True}
        )
        submission = prepare_rf1086_submission(case, account)

        retryable = mark_retryable_failure(submission, code="GLD_004", message="token expired")
        stored = store_rf1086_feedback_and_receipt(
            submission,
            feedback_document_ids=("dialog-123", "feedback-456"),
            receipt_id="forsendelse-789",
        )

        self.assertEqual(retryable.status, SubmissionStatus.FAILED_RETRYABLE)
        self.assertEqual(stored.status, SubmissionStatus.RECEIPT_STORED)
        self.assertEqual(stored.feedback_document_ids, ("dialog-123", "feedback-456"))
        self.assertEqual(stored.receipt_id, "forsendelse-789")

    def test_production_mode_requires_security_step_up_and_review_gate(self) -> None:
        case = FilingCase.from_json_file(FIXTURE_DIR / "stiftelse.json")
        account = assign_standard_pricing(case.company.org_number).model_copy(
            update={"subscription_active": True, "filing_package_paid": True}
        )

        with self.assertRaisesRegex(PermissionError, "security context"):
            prepare_rf1086_submission(case, account, mode=Rf1086SubmissionMode.PRODUCTION)
        with self.assertRaisesRegex(PermissionError, "human security review"):
            prepare_rf1086_submission(
                case,
                account,
                mode=Rf1086SubmissionMode.PRODUCTION,
                security_context=StepUpContext(
                    actor_id="owner",
                    mfa_verified_at=datetime.now(UTC),
                    security_review_approved=False,
                    production_credentials_enabled=True,
                ),
            )

        prepared = prepare_rf1086_submission(
            case,
            account,
            mode=Rf1086SubmissionMode.PRODUCTION,
            security_context=StepUpContext(
                actor_id="owner",
                mfa_verified_at=datetime.now(UTC),
                security_review_approved=True,
                production_credentials_enabled=True,
            ),
        )

        self.assertEqual(prepared.status, SubmissionStatus.READY)


if __name__ == "__main__":
    unittest.main()
