from __future__ import annotations

from datetime import date
import unittest

from pydantic import ValidationError

from holding_core.holding_actions import (
    AdminCostCategory,
    AdminCostInput,
    DocumentStatus,
    OpeningBalanceInput,
    ShareholderLoanDirection,
    ShareholderLoanInput,
    build_admin_cost_entry,
    build_opening_balance_entry,
    build_shareholder_loan,
)
from holding_core.ledger import AuditAction, LedgerLine, NarrowLedger


class NarrowLedgerTest(unittest.TestCase):
    def test_draft_posting_and_reversal_lifecycle(self) -> None:
        ledger = NarrowLedger()
        draft = build_admin_cost_entry(
            AdminCostInput(
                company_id="314259521",
                paid_date=date(2025, 2, 1),
                amount=590,
                payee="Banken",
                category=AdminCostCategory.BANK_FEE,
                document_status=DocumentStatus.NOT_REQUIRED,
            )
        )

        ledger.create_draft(draft)
        updated = ledger.update_draft(draft.id, memo="Monthly bank fee")
        posted = ledger.post(updated.id)
        reversal = ledger.reverse_posted(posted.id, entry_date=date(2025, 2, 2), memo="Reverse bank fee")

        self.assertEqual(len(ledger.drafts), 0)
        self.assertEqual(len(ledger.filing_source_entries("314259521")), 2)
        self.assertEqual(reversal.reverses_entry_id, posted.id)
        self.assertEqual(
            [event.action for event in ledger.audit_events],
            [
                AuditAction.DRAFT_CREATED,
                AuditAction.DRAFT_UPDATED,
                AuditAction.ENTRY_POSTED,
                AuditAction.ENTRY_REVERSED,
                AuditAction.ENTRY_POSTED,
            ],
        )

        with self.assertRaises(ValidationError):
            posted.memo = "Cannot mutate posted entry"

    def test_unbalanced_draft_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_opening_balance_entry(
                OpeningBalanceInput(
                    company_id="314259521",
                    opening_date=date(2025, 1, 1),
                    bank_balance=100,
                    share_capital=50,
                )
            )

        with self.assertRaises(ValueError):
            LedgerLine(account="1920", description="bad", debit=10, credit=10)


class HoldingActionTest(unittest.TestCase):
    def test_opening_balance_posts_new_year_start(self) -> None:
        ledger = NarrowLedger()
        draft = build_opening_balance_entry(
            OpeningBalanceInput(
                company_id="314259521",
                opening_date=date(2025, 1, 1),
                bank_balance=30000,
                share_investments=70000,
                shareholder_loan_payable=20000,
                share_capital=30000,
                retained_earnings=50000,
                prior_annual_accounts_reference="2024 annual accounts uploaded",
            )
        )

        ledger.create_draft(draft)
        posted = ledger.post(draft.id)

        self.assertEqual(posted.source, "holding_action:opening_balance")
        self.assertEqual(sum(line.debit for line in posted.lines), 100000)
        self.assertEqual(sum(line.credit for line in posted.lines), 100000)

    def test_admin_cost_scope_and_document_status(self) -> None:
        draft = build_admin_cost_entry(
            AdminCostInput(
                company_id="314259521",
                paid_date=date(2025, 3, 1),
                amount=1490,
                payee="Talli AS",
                category=AdminCostCategory.SOFTWARE,
                document_status=DocumentStatus.MISSING_ACCEPTED_WARNING,
            )
        )

        self.assertIn("document:missing_accepted_warning", draft.source)
        self.assertEqual(draft.lines[0].account, "6420")
        self.assertEqual(draft.lines[1].account, "1920")

        with self.assertRaises(ValidationError):
            AdminCostInput(
                company_id="314259521",
                paid_date=date(2025, 3, 1),
                amount=1490,
                payee="VAT Vendor",
                category=AdminCostCategory.SOFTWARE,
                document_status=DocumentStatus.ATTACHED,
                vat_deduction=298,
            )

    def test_shareholder_loan_records_supported_direction_and_blocks_high_risk(self) -> None:
        entry = build_shareholder_loan(
            ShareholderLoanInput(
                company_id="314259521",
                loan_date=date(2025, 7, 1),
                amount=20000,
                direction=ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
                counterparty_name="Ola Nordmann",
                document_status=DocumentStatus.ATTACHED,
                interest_modelled=True,
            )
        )

        self.assertEqual(entry.lines[0].account, "1920")
        self.assertEqual(entry.lines[1].account, "2255")
        self.assertIn("direction:shareholder_to_company", entry.source)

        with self.assertRaises(ValidationError):
            ShareholderLoanInput(
                company_id="314259521",
                loan_date=date(2025, 7, 1),
                amount=20000,
                direction=ShareholderLoanDirection.COMPANY_TO_PERSONAL_SHAREHOLDER,
                counterparty_name="Ola Nordmann",
                document_status=DocumentStatus.ATTACHED,
            )


if __name__ == "__main__":
    unittest.main()
