from __future__ import annotations

from datetime import date
import unittest

from pydantic import ValidationError

from holding_core.holding_actions import (
    AdminCostCategory,
    AdminCostInput,
    DividendReceivedInput,
    DocumentStatus,
    InvestmentKind,
    OpeningBalanceInput,
    SharePurchaseInput,
    ShareSaleInput,
    ShareholderLoanDirection,
    ShareholderLoanInput,
    TaxTreatment,
    build_admin_cost_entry,
    build_dividend_received,
    build_opening_balance_entry,
    build_share_purchase,
    build_share_sale,
    build_shareholder_loan,
)
from holding_core.investment_lots import AcquisitionLot
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

    def test_dividend_received_calculates_fritaksmetoden_add_back(self) -> None:
        result = build_dividend_received(
            DividendReceivedInput(
                company_id="314259521",
                declared_date=date(2025, 4, 1),
                paid_date=date(2025, 4, 15),
                gross_amount=100000,
                paying_company_name="PORTFOLIO AS",
                linked_investment_id="portfolio-as",
                tax_treatment=TaxTreatment.FRITAKSMETODEN,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
        )

        self.assertEqual(result.taxable_add_back, 3000)
        self.assertIn("tax:fritaksmetoden", result.entry.source)
        self.assertIn("bank_matched:true", result.entry.source)
        self.assertEqual(result.entry.lines[0].account, "1920")
        self.assertEqual(result.entry.lines[1].account, "8070")

        with self.assertRaises(ValidationError):
            DividendReceivedInput(
                company_id="314259521",
                declared_date=date(2025, 4, 1),
                paid_date=date(2025, 4, 15),
                gross_amount=100000,
                paying_company_name="UNCLEAR FUND",
                linked_investment_id="unclear-fund",
                tax_treatment=TaxTreatment.NEEDS_ACCOUNTANT,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )

    def test_share_purchase_creates_position_and_blocks_unclear_tax(self) -> None:
        result = build_share_purchase(
            SharePurchaseInput(
                company_id="314259521",
                investment_id="portfolio-as",
                investment_name="PORTFOLIO AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=TaxTreatment.FRITAKSMETODEN,
                acquisition_date=date(2025, 5, 1),
                share_count=100,
                purchase_amount=50000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
                org_number="999888777",
            )
        )

        self.assertEqual(result.position.cost_basis, 50000)
        self.assertEqual(result.position.share_count, 100)
        self.assertEqual(result.entry.lines[0].account, "1800")
        self.assertIn("holding_action:share_purchase", result.entry.source)

        with self.assertRaises(ValidationError):
            SharePurchaseInput(
                company_id="314259521",
                investment_id="complex",
                investment_name="COMPLEX AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=TaxTreatment.NEEDS_ACCOUNTANT,
                acquisition_date=date(2025, 5, 1),
                share_count=100,
                purchase_amount=50000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )

    def test_share_sale_reduces_position_and_calculates_gain(self) -> None:
        purchase = build_share_purchase(
            SharePurchaseInput(
                company_id="314259521",
                investment_id="portfolio-as",
                investment_name="PORTFOLIO AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=TaxTreatment.FRITAKSMETODEN,
                acquisition_date=date(2025, 5, 1),
                share_count=100,
                purchase_amount=50000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
        )
        sale = build_share_sale(
            ShareSaleInput(
                company_id="314259521",
                position=purchase.position,
                sale_date=date(2025, 8, 1),
                sold_share_count=40,
                proceeds=30000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
        )

        self.assertEqual(sale.updated_position.share_count, 60)
        self.assertEqual(sale.updated_position.cost_basis, 30000)
        self.assertEqual(sale.gain_or_loss, 10000)
        self.assertIn("gain_or_loss:10000", sale.entry.source)

        with self.assertRaises(ValidationError):
            ShareSaleInput(
                company_id="314259521",
                position=purchase.position,
                sale_date=date(2025, 8, 1),
                sold_share_count=101,
                proceeds=30000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )

    def test_share_sale_consumes_acquisition_lots_fifo(self) -> None:
        position = build_share_purchase(
            SharePurchaseInput(
                company_id="314259521",
                investment_id="portfolio-as",
                investment_name="PORTFOLIO AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=TaxTreatment.FRITAKSMETODEN,
                acquisition_date=date(2025, 1, 1),
                share_count=200,
                purchase_amount=40000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
        ).position
        sale = build_share_sale(
            ShareSaleInput(
                company_id="314259521",
                position=position,
                acquisition_lots=(
                    AcquisitionLot(
                        id="lot-new",
                        acquisition_date=date(2025, 2, 1),
                        original_share_count=100,
                        remaining_share_count=100,
                        original_cost_basis=30000,
                        remaining_cost_basis=30000,
                    ),
                    AcquisitionLot(
                        id="lot-old",
                        acquisition_date=date(2025, 1, 1),
                        original_share_count=100,
                        remaining_share_count=100,
                        original_cost_basis=10000,
                        remaining_cost_basis=10000,
                    ),
                ),
                sale_date=date(2025, 3, 1),
                sold_share_count=150,
                proceeds=30000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
        )

        self.assertEqual(sale.cost_basis_reduction, 25000)
        self.assertEqual(sale.gain_or_loss, 5000)
        self.assertEqual(sale.updated_position.cost_basis, 15000)
        self.assertEqual([allocation.lot_id for allocation in sale.lot_allocations], ["lot-old", "lot-new"])

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
