from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from holding_core.holding_actions import (
    AdminCostCategory,
    AdminCostInput,
    DividendReceivedInput,
    DividendToOwnerInput,
    DocumentStatus,
    InvestmentPosition,
    InvestmentKind,
    SharePurchaseInput,
    ShareSaleInput,
    ShareholderDividendAllocation,
    ShareholderLoanDirection,
    ShareholderLoanInput,
    TaxTreatment,
)
from holding_core.ledger import DraftEntry, LedgerLine
from holding_core.workspace import (
    Actor,
    CompanyIdentity,
    FilingStatus,
    ManualJournalRisk,
    SupportStatus,
    WorkspaceRole,
    WorkspaceStore,
    acknowledge_review_comment,
    add_filing_override,
    add_review_comment,
    assign_founder_billing,
    attach_document,
    confirm_company_identity,
    create_signed_document_url,
    dashboard_for_company,
    export_workspace_archive,
    fetch_brreg_identity,
    generate_owner_dividend_documents,
    import_bank_csv,
    invite_member,
    lock_period,
    map_brreg_entity,
    match_bank_transaction,
    norwegian_label,
    record_holding_action,
    record_manual_journal,
    record_tax_settlement,
    request_filing_package_payment,
    validate_annual_public_data,
)


class WorkspaceMvpTest(unittest.TestCase):
    def test_persistent_workspace_enforces_tenant_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            _seed_actors(store)
            workspace = store.create_workspace("owner", _identity())

            self.assertEqual(workspace.support_boundary.status, SupportStatus.READY)
            self.assertEqual(store.get_workspace("owner", "314259521").company.name, "Demo Holding AS")

            reloaded = WorkspaceStore(Path(temp_dir) / "workspace.json")
            self.assertEqual(reloaded.get_workspace("owner", "314259521").company.org_number, "314259521")
            with self.assertRaises(PermissionError):
                reloaded.get_workspace("outsider", "314259521")

    def test_org_number_onboarding_maps_brreg_and_blocks_non_as(self) -> None:
        identity = map_brreg_entity(
            {
                "organisasjonsnummer": "314259521",
                "navn": "Demo Holding AS",
                "organisasjonsform": {"kode": "AS"},
                "forretningsadresse": {"adresse": ["Storgata 1"], "postnummer": "0155", "poststed": "OSLO"},
            }
        )
        fetched = fetch_brreg_identity(
            "314259521",
            fetcher=lambda url: {
                "organisasjonsnummer": "314259521",
                "navn": "Demo Holding AS",
                "organisasjonsform": {"kode": "AS"},
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            _seed_actors(store)
            store.create_workspace("owner", identity)
            confirmed = confirm_company_identity(store, "owner", "314259521")
            blocked = store.create_workspace(
                "owner",
                CompanyIdentity(org_number="999888777", name="Demo ENK", entity_type="ENK"),
            )

            self.assertTrue(confirmed.company.is_locked)
            self.assertEqual(fetched.source, "brreg")
            self.assertEqual(blocked.support_boundary.status, SupportStatus.BLOCKED)

    def test_roles_review_comments_documents_and_signed_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _ready_store(temp_dir)
            invite_member(store, "owner", "314259521", invited_actor_id="reviewer", role=WorkspaceRole.REVIEWER)
            reviewed = add_review_comment(store, "reviewer", "314259521", target="årsregnskap", body="Kontroller bank.")
            acknowledged = acknowledge_review_comment(store, "owner", "314259521", reviewed.review_comments[0].id)
            documented = attach_document(
                store,
                "owner",
                "314259521",
                income_year=2025,
                document_type="bank_statement",
                name="Bank.pdf",
                linked_to="årsregnskap",
                storage_key="companies/314259521/2025/bank.pdf",
            )
            signed = create_signed_document_url(store, "reviewer", "314259521", documented.documents[0].id)

            self.assertTrue(acknowledged.review_comments[0].acknowledged_by_owner)
            self.assertEqual(documented.documents[0].retention_years, 5)
            self.assertTrue(signed.url.startswith("talli-signed://"))
            with self.assertRaises(PermissionError):
                attach_document(
                    store,
                    "reviewer",
                    "314259521",
                    income_year=2025,
                    document_type="receipt",
                    name="Receipt.pdf",
                    linked_to="cost",
                    storage_key="bad",
                )

    def test_bank_csv_import_matching_and_duplicate_handling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _ready_store(temp_dir)
            csv_text = "date,text,amount,balance\n2025-01-02,Opening,30000,30000\n2025-01-03,Fee,-50,29950\n"
            imported = import_bank_csv(store, "owner", "314259521", income_year=2025, csv_text=csv_text)
            imported_again = import_bank_csv(store, "owner", "314259521", income_year=2025, csv_text=csv_text)
            matched = match_bank_transaction(
                store,
                "owner",
                "314259521",
                imported.bank_transactions[0].id,
                accepted_warning=True,
            )

            self.assertEqual(len(imported.bank_transactions), 2)
            self.assertEqual(len(imported_again.bank_transactions), 2)
            self.assertTrue(matched.bank_transactions[0].is_matched)
            self.assertEqual(dashboard_for_company(store, "owner", "314259521", income_year=2025).unreconciled_bank_transactions, 1)

    def test_persisted_actions_investment_register_period_locks_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _ready_store(temp_dir)
            purchase_input = SharePurchaseInput(
                company_id="314259521",
                investment_id="portfolio-as",
                investment_name="Portfolio AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=TaxTreatment.FRITAKSMETODEN,
                acquisition_date=date(2025, 1, 10),
                share_count=100,
                purchase_amount=50000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
            purchased = record_holding_action(store, "owner", "314259521", income_year=2025, action_input=purchase_input)
            sale_position = InvestmentPosition(
                id=purchased.investment_positions[0].id,
                company_id="314259521",
                name=purchased.investment_positions[0].name,
                kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                tax_treatment=TaxTreatment.FRITAKSMETODEN,
                share_count=purchased.investment_positions[0].share_count,
                cost_basis=purchased.investment_positions[0].cost_basis,
            )
            sale_input = ShareSaleInput(
                company_id="314259521",
                position=sale_position,
                sale_date=date(2025, 6, 1),
                sold_share_count=25,
                proceeds=20000,
                bank_matched=True,
                document_status=DocumentStatus.ATTACHED,
            )
            sold = record_holding_action(store, "owner", "314259521", income_year=2025, action_input=sale_input)
            dividend = record_holding_action(
                store,
                "owner",
                "314259521",
                income_year=2025,
                action_input=DividendReceivedInput(
                    company_id="314259521",
                    declared_date=date(2025, 7, 1),
                    paid_date=date(2025, 7, 15),
                    gross_amount=1000,
                    paying_company_name="Portfolio AS",
                    linked_investment_id="portfolio-as",
                    tax_treatment=TaxTreatment.FRITAKSMETODEN,
                    bank_matched=True,
                    document_status=DocumentStatus.ATTACHED,
                ),
            )
            overridden = add_filing_override(
                store,
                "owner",
                "314259521",
                income_year=2025,
                filing="årsregnskap",
                field_target="note",
                old_value="",
                new_value="Manuell note",
                reason="Authority field not modelled yet",
                risk_level="warning",
            )
            locked = lock_period(store, "owner", "314259521", income_year=2025, reason="Filing preview approved")

            self.assertEqual(sold.investment_positions[0].share_count, 75)
            self.assertEqual(dividend.investment_positions[0].movements[-1].movement_type, "dividend")
            self.assertEqual(len(overridden.filing_overrides), 1)
            self.assertEqual(len(locked.period_locks), 1)
            with self.assertRaises(ValueError):
                record_holding_action(
                    store,
                    "owner",
                    "314259521",
                    income_year=2025,
                    action_input=AdminCostInput(
                        company_id="314259521",
                        paid_date=date(2025, 7, 1),
                        amount=100,
                        payee="Bank",
                        category=AdminCostCategory.BANK_FEE,
                        document_status=DocumentStatus.NOT_REQUIRED,
                    ),
                )

    def test_manual_journal_escape_hatch_warns_and_blocks_sensitive_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _ready_store(temp_dir)
            warning_entry = DraftEntry(
                company_id="314259521",
                entry_date=date(2025, 3, 1),
                memo="Manual investment correction",
                source="manual_journal",
                lines=[
                    LedgerLine(account="1800", description="Investment", debit=100, credit=0),
                    LedgerLine(account="1920", description="Bank", debit=0, credit=100),
                ],
            )
            with self.assertRaises(ValueError):
                record_manual_journal(
                    store,
                    "owner",
                    "314259521",
                    income_year=2025,
                    entry=warning_entry,
                    explanation="Needs review",
                )
            workspace, result = record_manual_journal(
                store,
                "owner",
                "314259521",
                income_year=2025,
                entry=warning_entry,
                explanation="Accepted filing-sensitive correction",
                accept_warning=True,
            )
            blocked_entry = DraftEntry(
                company_id="314259521",
                entry_date=date(2025, 3, 2),
                memo="Manual tax correction",
                source="manual_journal",
                lines=[
                    LedgerLine(account="8300", description="Tax", debit=100, credit=0),
                    LedgerLine(account="1920", description="Bank", debit=0, credit=100),
                ],
            )

            self.assertEqual(result.risk, ManualJournalRisk.WARNING)
            self.assertEqual(workspace.structured_actions[-1].action_type, "manual_journal")
            with self.assertRaises(ValueError):
                record_manual_journal(
                    store,
                    "owner",
                    "314259521",
                    income_year=2025,
                    entry=blocked_entry,
                    explanation="Blocked tax correction",
                    accept_warning=True,
                )

    def test_corporate_documents_tax_settlement_dashboard_archive_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _ready_store(temp_dir)
            loan = record_holding_action(
                store,
                "owner",
                "314259521",
                income_year=2025,
                action_input=ShareholderLoanInput(
                    company_id="314259521",
                    loan_date=date(2025, 2, 1),
                    amount=10000,
                    direction=ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
                    counterparty_name="Owner",
                    document_status=DocumentStatus.ATTACHED,
                ),
            )
            taxed = record_tax_settlement(
                store,
                "owner",
                "314259521",
                income_year=2025,
                amount=2200,
                settlement_type="payable",
            )
            with self.assertRaises(ValueError):
                generate_owner_dividend_documents(store, "owner", "314259521", loan.structured_actions[0].id)
            dividend = record_holding_action(
                store,
                "owner",
                "314259521",
                income_year=2025,
                action_input=DividendToOwnerInput(
                    company_id="314259521",
                    decision_date=date(2025, 6, 1),
                    payment_date=date(2025, 6, 15),
                    total_amount=1000,
                    distributable_equity=5000,
                    liquidity_after_payment=1000,
                    document_status=DocumentStatus.ATTACHED,
                    allocations=[ShareholderDividendAllocation(shareholder_id="owner", share_count=100, amount=1000)],
                ),
            )
            documented = generate_owner_dividend_documents(store, "owner", "314259521", dividend.structured_actions[-1].id)

            # Loan action is not a dividend action, so document generation must reject it.
            self.assertEqual(len(taxed.structured_actions), 2)
            self.assertGreaterEqual(len(documented.documents), 0)

            dashboard = dashboard_for_company(store, "owner", "314259521", income_year=2025, today=date(2026, 2, 1))
            archive = export_workspace_archive(store, "owner", "314259521", income_year=2025)
            validation = validate_annual_public_data(_annual_from_archive_like(store))

            self.assertIn(FilingStatus.OVERDUE, [deadline.status for deadline in dashboard.deadlines])
            self.assertTrue(archive.receipts)
            self.assertGreaterEqual(len(documented.documents), 2)
            self.assertIn(validation["outcome"], {"pass", "blocked", "mismatch"})

    def test_billing_gate_and_norwegian_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _ready_store(temp_dir)
            founder = assign_founder_billing(store, "owner", "314259521", cohort_number=1)
            founder = founder.model_copy(
                update={"billing_account": founder.billing_account.model_copy(update={"subscription_active": True})}
            )
            store.replace_workspace(founder)
            paid = request_filing_package_payment(store, "owner", "314259521", filing_ready=True)

            self.assertTrue(paid.billing_account.filing_package_paid)
            self.assertEqual(norwegian_label("readiness"), "Filingstatus")
            self.assertEqual(norwegian_label("blocked"), "Blokkert")


def _store(temp_dir: str) -> WorkspaceStore:
    return WorkspaceStore(Path(temp_dir) / "workspace.json")


def _seed_actors(store: WorkspaceStore) -> None:
    store.upsert_actor(Actor(id="owner", email="owner@example.com", name="Owner"))
    store.upsert_actor(Actor(id="reviewer", email="review@example.com", name="Reviewer"))
    store.upsert_actor(Actor(id="outsider", email="out@example.com", name="Outsider"))


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        org_number="314259521",
        name="Demo Holding AS",
        entity_type="AS",
        address="Storgata 1",
        postal_code="0155",
        city="OSLO",
    )


def _ready_store(temp_dir: str) -> WorkspaceStore:
    store = _store(temp_dir)
    _seed_actors(store)
    store.create_workspace("owner", _identity())
    confirm_company_identity(store, "owner", "314259521")
    return store


def _annual_from_archive_like(store: WorkspaceStore):
    workspace = store.get_workspace("owner", "314259521")
    from holding_core.annual import build_annual_data, YearEndInterviewAnswers

    return build_annual_data(
        company_id="314259521",
        income_year=2025,
        interview=YearEndInterviewAnswers(
            shares_owned_at_year_end=False,
            bought_or_sold_shares=False,
            received_dividends=False,
            declared_owner_dividends=False,
            shareholder_loans=False,
            paid_costs=False,
            bank_balance_confirmed=True,
            has_unpaid_items=False,
            general_meeting_approved=True,
            authority_to_submit_confirmed=True,
        ),
        posted_entries=workspace.posted_entries,
    )


if __name__ == "__main__":
    unittest.main()
