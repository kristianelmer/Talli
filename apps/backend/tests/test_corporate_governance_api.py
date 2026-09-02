from __future__ import annotations

from base64 import b64decode
from datetime import date

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.ledger.public import (
    PostedLedgerEntry,
)
from talli_backend.shared.kernel import Money

from test_corporate_governance import supported_annual_close, supported_proposal
from test_corporate_governance_workflow import (
    DocumentsSessionFactoryStub,
    DocumentsSessionStub,
    GovernanceSessionFactoryStub,
    GovernanceSessionStub,
    GovernanceTransactionStub,
    NOW,
)


class ApiGovernanceTransaction(GovernanceTransactionStub):
    async def post_entry(self, command, **kwargs):
        self.calls.append(("post_entry", command))
        return PostedLedgerEntry(
            kwargs["requested_entry_id"],
            command.company_id,
            command.income_year,
            kwargs["entry_kind"],
            NOW,
            False,
        )


def client_and_transaction(*, annual_documents: bool = False):
    transaction = ApiGovernanceTransaction()
    governance_sessions = GovernanceSessionFactoryStub(
        GovernanceSessionStub(transaction)
    )
    documents = DocumentsSessionStub()
    if annual_documents:
        documents.records[0].linked_to = (
            "corporate_decision:44444444-4444-4444-8444-444444444444"
        )
        documents.records[0].content_sha256 = (
            "dc38c0c178f4a0bbd7e466581fae416d6ddeabfacf00027eaac95dbe7ad28e50"
        )
        documents.records[0].byte_length = 32066
        documents.records[1].content_sha256 = (
            "270bf87a72e5ced5b13490e220e352bde7a16bff019f48d46bfa88ac1d561776"
        )
        documents.records[1].linked_to = (
            "corporate_decision:44444444-4444-4444-8444-444444444444"
        )
        documents.records[1].byte_length = 32626
    documents_sessions = DocumentsSessionFactoryStub(documents)
    return (
        TestClient(
            create_app(
                corporate_governance_session_factory=governance_sessions,
                documents_session_factory=documents_sessions,
            )
        ),
        transaction,
    )


def proposal_payload() -> dict[str, object]:
    command = supported_proposal()
    return {
        "companyId": str(command.company_id),
        "incomeYear": int(command.income_year),
        "decisionId": str(command.decision_id),
        "documentSetId": str(command.document_set_id),
        "company": {
            "organizationNumber": command.company.organization_number,
            "legalName": command.company.legal_name,
        },
        "shareholders": [
            {
                "shareholderId": item.shareholder_id,
                "name": item.name,
                "shareCount": item.share_count,
                "order": item.order,
            }
            for item in command.shareholders
        ],
        "annualBasis": {
            "sourceId": str(command.annual_basis.source_id),
            "incomeYear": int(command.annual_basis.income_year),
            "latestApproved": command.annual_basis.latest_approved,
            "annualDataSha256": command.annual_basis.annual_data_sha256,
            "annualAccountsPayloadSha256": (
                command.annual_basis.annual_accounts_payload_sha256
            ),
            "resultAfterTaxOre": command.annual_basis.result_after_tax_ore,
            "equityOre": command.annual_basis.equity_ore,
            "availableDistributionOre": (
                command.annual_basis.available_distribution_ore
            ),
            "cashOre": command.annual_basis.cash_ore,
        },
        "reviewedFacts": {
            "organizationNumber": command.reviewed_facts.organization_number,
            "legalName": command.reviewed_facts.legal_name,
            "shareholders": [
                {
                    "shareholderId": item.shareholder_id,
                    "name": item.name,
                    "shareCount": item.share_count,
                }
                for item in command.reviewed_facts.shareholders
            ],
            "totalCompanyShares": command.reviewed_facts.total_company_shares,
            "availableDistributionOre": (
                command.reviewed_facts.available_distribution_ore
            ),
            "annualDataSha256": command.reviewed_facts.annual_data_sha256,
            "annualAccountsPayloadSha256": (
                command.reviewed_facts.annual_accounts_payload_sha256
            ),
        },
        "boardMeeting": {
            "meetingDate": command.board_meeting.meeting_date.value.isoformat(),
            "meetingTime": command.board_meeting.meeting_time.isoformat(),
            "place": command.board_meeting.place,
            "treatmentMethod": command.board_meeting.treatment_method.value,
        },
        "boardParticipants": [
            {
                "participantId": item.participant_id,
                "name": item.name,
                "role": item.role.value,
                "order": item.order,
            }
            for item in command.board_participants
        ],
        "generalMeeting": {
            "meetingDate": command.general_meeting.meeting_date.value.isoformat(),
            "meetingTime": command.general_meeting.meeting_time.isoformat(),
            "place": command.general_meeting.place,
            "meetingForm": command.general_meeting.meeting_form.value,
            "chairName": command.general_meeting.chair_name,
            "coSignerName": command.general_meeting.co_signer_name,
        },
        "shareholderBallots": [
            {
                "shareholderId": item.shareholder_id,
                "representedShareCount": item.represented_share_count,
                "vote": item.vote.value,
            }
            for item in command.shareholder_ballots
        ],
        "oneShareClassConfirmed": command.one_share_class_confirmed,
        "fullBoardParticipationConfirmed": (command.full_board_participation_confirmed),
        "unanimousBoardConfirmed": command.unanimous_board_confirmed,
        "supportedDividendBasisConfirmed": (command.supported_dividend_basis_confirmed),
        "prudentEquityAndLiquidityConfirmed": (
            command.prudent_equity_and_liquidity_confirmed
        ),
        "dividendAmountOre": command.dividend_amount_ore,
        "paymentDate": command.payment_date.value.isoformat(),
    }


def annual_close_payload() -> dict[str, object]:
    command = supported_annual_close()
    payload = proposal_payload()
    payload = {
        **payload,
        "incomeYear": int(command.income_year),
        "decisionId": str(command.decision_id),
        "documentSetId": str(command.document_set_id),
        "annualBasis": {
            **payload["annualBasis"],
            "incomeYear": int(command.annual_basis.income_year),
        },
        "boardMeeting": {
            **payload["boardMeeting"],
            "meetingDate": command.board_meeting.meeting_date.value.isoformat(),
        },
        "generalMeeting": {
            **payload["generalMeeting"],
            "meetingDate": command.general_meeting.meeting_date.value.isoformat(),
        },
        "annualResultAllocationOre": command.annual_result_allocation_ore,
    }
    del payload["dividendAmountOre"]
    del payload["paymentDate"]
    return payload


def headers(key: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer access-token",
        "Idempotency-Key": key,
        "X-Request-ID": key,
    }


def test_owner_dividend_fastapi_lifecycle_is_typed_and_backend_owned() -> None:
    client, transaction = client_and_transaction()
    proposal = proposal_payload()
    decision_id = proposal["decisionId"]

    proposed = client.post(
        "/api/v1/corporate-governance/owner-dividends/proposals",
        headers=headers("owner-dividend-proposal-0001"),
        json=proposal,
    )
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["decision"]["decisionHash"]
    decision_hash = proposed.json()["decision"]["decisionHash"]

    registered = client.post(
        f"/api/v1/corporate-governance/owner-dividends/{decision_id}/documents",
        headers=headers("owner-dividend-documents-0001"),
        json={
            "companyId": proposal["companyId"],
            "documentSetId": proposal["documentSetId"],
            "decisionHash": decision_hash,
            "artifacts": [
                {
                    "artifactId": "88888888-8888-4888-8888-888888888881",
                    "documentId": "66666666-6666-4666-8666-666666666666",
                    "artifactKind": "dividend_board_proposal",
                    "contentSha256": "a" * 64,
                    "byteLength": 101,
                },
                {
                    "artifactId": "88888888-8888-4888-8888-888888888882",
                    "documentId": "77777777-7777-4777-8777-777777777777",
                    "artifactKind": "dividend_general_meeting_minutes",
                    "contentSha256": "b" * 64,
                    "byteLength": 202,
                },
            ],
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["state"] == "documents_registered"

    approved = client.post(
        f"/api/v1/corporate-governance/owner-dividends/{decision_id}/approvals",
        headers=headers("owner-dividend-approval-0001"),
        json={
            "companyId": proposal["companyId"],
            "documentSetId": proposal["documentSetId"],
            "decisionHash": decision_hash,
            "approvalEventId": "eeeeeeee-1111-4111-8111-111111111111",
        },
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["state"] == "facts_approved"

    finalized = client.post(
        f"/api/v1/corporate-governance/owner-dividends/{decision_id}/finalizations",
        headers=headers("owner-dividend-finalization-0001"),
        json={
            "companyId": proposal["companyId"],
            "incomeYear": proposal["incomeYear"],
            "documentSetId": proposal["documentSetId"],
            "decisionHash": decision_hash,
            "finalizationId": "55555555-5555-4555-8555-555555555555",
            "holdingActionId": "aaaaaaaa-1111-4111-8111-111111111111",
            "ledgerEntryId": "99999999-9999-4999-8999-999999999999",
        },
    )
    assert finalized.status_code == 201, finalized.text
    assert finalized.json()["state"] == "finalized"
    posted = [call for call in transaction.calls if call[0] == "post_entry"][-1][1]
    assert posted.declared_amount == Money.nok("100000.01")

    paid = client.post(
        f"/api/v1/corporate-governance/owner-dividends/{decision_id}/payments",
        headers=headers("owner-dividend-payment-0001"),
        json={
            "companyId": proposal["companyId"],
            "incomeYear": proposal["incomeYear"],
            "documentSetId": proposal["documentSetId"],
            "decisionHash": decision_hash,
            "paymentEventId": "bbbbbbbb-1111-4111-8111-111111111111",
            "holdingActionId": "cccccccc-1111-4111-8111-111111111111",
            "ledgerEntryId": "99999999-9999-4999-8999-999999999999",
            "bankTransactionId": "dddddddd-1111-4111-8111-111111111111",
        },
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["state"] == "partially_paid"
    bank_claim = [call for call in transaction.calls if call[0] == "claim_bank"][-1]
    assert bank_claim[1][0].transaction_date.value == date(2025, 7, 2)


def test_annual_close_fastapi_proposal_is_typed_and_backend_owned() -> None:
    client, transaction = client_and_transaction(annual_documents=True)
    proposed = client.post(
        "/api/v1/corporate-governance/annual-closes/proposals",
        headers=headers("annual-close-proposal-0001"),
        json=annual_close_payload(),
    )
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["decision"]["decisionKind"] == "annual_close"
    assert proposed.json()["decision"]["decisionHash"] == (
        "2e364c248ed1d6894fd69e69b82012ddddb492d572db5e377b05988ee8349eaa"
    )
    assert proposed.json()["decision"]["dividend"] is None
    assert [artifact["artifactKind"] for artifact in proposed.json()["artifacts"]] == [
        "annual_board_minutes",
        "annual_general_meeting_minutes",
    ]
    assert [artifact["contentSha256"] for artifact in proposed.json()["artifacts"]] == [
        "dc38c0c178f4a0bbd7e466581fae416d6ddeabfacf00027eaac95dbe7ad28e50",
        "270bf87a72e5ced5b13490e220e352bde7a16bff019f48d46bfa88ac1d561776",
    ]
    assert all(
        b64decode(artifact["contentBase64"]).startswith(b"%PDF-")
        for artifact in proposed.json()["artifacts"]
    )
    assert transaction.calls[-1][0] == "propose_annual_close"

    registered = client.post(
        f"/api/v1/corporate-governance/annual-closes/{annual_close_payload()['decisionId']}/documents",
        headers=headers("annual-close-documents-0001"),
        json={
            "companyId": annual_close_payload()["companyId"],
            "documentSetId": annual_close_payload()["documentSetId"],
            "decisionHash": proposed.json()["decision"]["decisionHash"],
            "artifacts": [
                {
                    "artifactId": artifact_id,
                    "documentId": document_id,
                    "artifactKind": artifact["artifactKind"],
                    "contentSha256": artifact["contentSha256"],
                    "byteLength": artifact["byteLength"],
                }
                for artifact, artifact_id, document_id in zip(
                    proposed.json()["artifacts"],
                    (
                        "88888888-8888-4888-8888-888888888881",
                        "88888888-8888-4888-8888-888888888882",
                    ),
                    (
                        "66666666-6666-4666-8666-666666666666",
                        "77777777-7777-4777-8777-777777777777",
                    ),
                    strict=True,
                )
            ],
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["state"] == "documents_registered"
    assert registered.json()["generatedArtifactHashes"] == {
        artifact["artifactKind"]: artifact["contentSha256"]
        for artifact in proposed.json()["artifacts"]
    }


def test_owner_dividend_routes_require_bearer_and_reject_extra_fields() -> None:
    client, _ = client_and_transaction()
    payload = proposal_payload()
    missing = client.post(
        "/api/v1/corporate-governance/owner-dividends/proposals",
        headers={"Idempotency-Key": "owner-dividend-proposal-0001"},
        json=payload,
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "AUTHENTICATION_REQUIRED"

    invalid = client.post(
        "/api/v1/corporate-governance/owner-dividends/proposals",
        headers=headers("owner-dividend-proposal-0001"),
        json={**payload, "accountingPolicyVersion": "browser-choice"},
    )
    assert invalid.status_code == 422


def test_shareholder_loan_fastapi_is_governance_owned_and_strict() -> None:
    client, transaction = client_and_transaction()
    payload = {
        "companyId": str(supported_proposal().company_id),
        "incomeYear": 2025,
        "actionId": "12121212-1212-4212-8212-121212121212",
        "ledgerEntryId": "13131313-1313-4313-8313-131313131313",
        "loanDate": "2025-03-01",
        "amount": {"amount": "1250.50", "currency": "NOK"},
        "direction": "shareholder_to_company",
        "counterpartyName": "Eier Holding AS",
        "documentStatus": "attached",
        "interestModelled": True,
        "relatedPartySecurity": False,
        "bankTransactionId": None,
        "documentId": None,
    }
    response = client.post(
        "/api/v1/corporate-governance/shareholder-loans",
        headers=headers("shareholder-loan-record-0001"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    assert response.json() == {
        "actionId": payload["actionId"],
        "companyId": payload["companyId"],
        "incomeYear": 2025,
        "loanDate": "2025-03-01",
        "amountOre": 125050,
        "direction": "shareholder_to_company",
        "counterpartyName": "Eier Holding AS",
        "documentStatus": "attached",
        "interestModelled": True,
        "relatedPartySecurity": False,
        "bankTransactionId": None,
        "documentId": None,
        "accountingEntryId": payload["ledgerEntryId"],
        "replayed": False,
    }
    assert [call for call in transaction.calls if call[0] == "post_entry"]

    rejected = client.post(
        "/api/v1/corporate-governance/shareholder-loans",
        headers=headers("shareholder-loan-record-0002"),
        json={**payload, "unexpected": True},
    )
    assert rejected.status_code == 422


def test_openapi_exposes_governance_operations() -> None:
    client, _ = client_and_transaction()
    schema = client.get("/api/v1/openapi.json").json()
    operations = {
        method["operationId"]
        for path in schema["paths"].values()
        for method in path.values()
        if isinstance(method, dict) and "operationId" in method
    }
    assert {
        "corporateGovernanceProposeOwnerDividend",
        "corporateGovernanceProposeAnnualClose",
        "corporateGovernanceRegisterOwnerDividendDocuments",
        "corporateGovernanceApproveOwnerDividend",
        "corporateGovernanceFinalizeOwnerDividend",
        "corporateGovernanceRecordOwnerDividendPayment",
        "corporateGovernanceRecordShareholderLoan",
    } <= operations
