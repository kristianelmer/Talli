from __future__ import annotations

import unittest
import uuid

from pydantic import ValidationError

from holding_core.billing import (
    BillingStatus,
    assign_founder_pricing,
    assign_standard_pricing,
    mark_supported_filing_failure,
    production_filing_gate,
)
from holding_core.submission import (
    SubmissionStatus,
    confirm_authority,
    confirm_preview,
    mark_blocked_failure,
    mark_retryable_failure,
    prepare_submission,
    register_api_call,
    store_receipt,
)


class SubmissionLifecycleTest(unittest.TestCase):
    def test_api_call_requires_authority_and_preview_confirmation(self) -> None:
        submission = prepare_submission(filing="aksjonærregisteroppgaven", company_id="999999999", income_year=2025)

        with self.assertRaisesRegex(ValueError, "authority and final preview"):
            register_api_call(submission, endpoint="/api/aksjonarregisteroppgave", body={"hello": "world"})

        submission = confirm_authority(submission, user_id="owner")
        submission = confirm_preview(submission, user_id="owner")
        submission = register_api_call(submission, endpoint="/api/aksjonarregisteroppgave", body={"hello": "world"})

        self.assertEqual(submission.status, SubmissionStatus.SUBMITTING)
        self.assertEqual(len(submission.calls), 1)

    def test_idempotency_key_is_reused_for_same_endpoint_and_body(self) -> None:
        submission = prepare_submission(filing="aksjonærregisteroppgaven", company_id="999999999", income_year=2025)
        submission = confirm_preview(confirm_authority(submission, user_id="owner"), user_id="owner")

        first = register_api_call(submission, endpoint="/hovedskjema", body={"a": 1})
        second = register_api_call(first, endpoint="/hovedskjema", body={"a": 1})
        third = register_api_call(second, endpoint="/hovedskjema", body={"a": 2})

        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 1)
        self.assertEqual(len(third.calls), 2)
        uuid.UUID(third.calls[0].idempotency_key)
        self.assertNotEqual(third.calls[0].idempotency_key, third.calls[1].idempotency_key)

    def test_receipt_and_failure_states_are_explicit(self) -> None:
        submission = prepare_submission(filing="årsregnskap", company_id="999999999", income_year=2025)
        retryable = mark_retryable_failure(submission, code="GLD_004", message="token expired")
        blocked = mark_blocked_failure(submission, code="GLD_1018", message="underskjema mismatch")
        stored = store_receipt(submission, receipt_id="receipt-123")

        self.assertEqual(retryable.status, SubmissionStatus.FAILED_RETRYABLE)
        self.assertEqual(blocked.status, SubmissionStatus.FAILED_BLOCKED)
        self.assertEqual(stored.status, SubmissionStatus.RECEIPT_STORED)
        self.assertEqual(stored.receipt_id, "receipt-123")


class BillingGateTest(unittest.TestCase):
    def test_founder_pricing_is_limited_to_first_100_companies(self) -> None:
        account = assign_founder_pricing("999999999", cohort_number=100)

        self.assertEqual(account.pricing.monthly_nok, 29)
        self.assertEqual(account.pricing.filing_package_nok, 299)

        with self.assertRaises(ValidationError):
            assign_founder_pricing("999999999", cohort_number=101)

    def test_unsupported_cases_are_not_charged(self) -> None:
        account = assign_standard_pricing("999999999").model_copy(
            update={"subscription_active": True, "supported_case": False}
        )

        gate = production_filing_gate(account, filing_ready=True)

        self.assertEqual(gate.status, BillingStatus.UNSUPPORTED_CASE)
        self.assertFalse(gate.allowed)
        self.assertFalse(gate.charge_allowed)

    def test_filing_package_is_charged_only_after_readiness(self) -> None:
        account = assign_standard_pricing("999999999").model_copy(update={"subscription_active": True})

        not_ready = production_filing_gate(account, filing_ready=False)
        ready_unpaid = production_filing_gate(account, filing_ready=True)
        ready_paid = production_filing_gate(account.model_copy(update={"filing_package_paid": True}), filing_ready=True)

        self.assertFalse(not_ready.charge_allowed)
        self.assertEqual(ready_unpaid.status, BillingStatus.FILING_PACKAGE_REQUIRED)
        self.assertTrue(ready_unpaid.charge_allowed)
        self.assertTrue(ready_paid.allowed)

    def test_supported_failure_becomes_refund_eligible(self) -> None:
        account = assign_standard_pricing("999999999").model_copy(
            update={"subscription_active": True, "filing_package_paid": True}
        )

        failed = mark_supported_filing_failure(account)

        self.assertTrue(failed.refund_eligible)


if __name__ == "__main__":
    unittest.main()
