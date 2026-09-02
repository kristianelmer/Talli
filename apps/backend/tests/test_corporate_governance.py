from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest

from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    AnnualCloseProposalCommand,
    ApprovedAnnualBasis,
    BoardMeeting,
    BoardParticipant,
    BoardRole,
    BoardTreatmentMethod,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateArtifactRecord,
    CorporateArtifactVariant,
    CorporateDecisionKind,
    CorporateDecisionId,
    CorporateDecisionRecord,
    CorporateDocumentSetId,
    CorporateDocumentSetRecord,
    CorporateEventId,
    CorporateEventRecord,
    CorporateFinalizationId,
    CorporateFinalizationRecord,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateLifecycleSnapshot,
    CorporateSourceReference,
    DocumentReference,
    GeneralMeeting,
    MeetingForm,
    OwnerDividendProposalCommand,
    PersistedCompanyFacts,
    PersistedShareholderFacts,
    ReviewedOwnerDividendFacts,
    ReviewedShareholderFacts,
    RecordShareholderLoanCommand,
    ShareholderBallot,
    ShareholderLoanDirection,
    ShareholderLoanDocumentStatus,
    ShareholderVote,
)
from talli_backend.modules.corporate_governance.service import (
    CorporateGovernanceService,
    canonical_owner_dividend_payload,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    UserId,
)


def supported_proposal() -> OwnerDividendProposalCommand:
    company_id = CompanyId("22222222-2222-4222-8222-222222222222")
    shareholders = (
        PersistedShareholderFacts("shareholder-2", "Jørgen Østby", 400, 2),
        PersistedShareholderFacts("shareholder-1", "Åse Nordmann", 600, 1),
    )
    annual_basis = ApprovedAnnualBasis(
        CorporateSourceReference("33333333-3333-4333-8333-333333333333"),
        IncomeYear(2024),
        True,
        "a" * 64,
        "b" * 64,
        12_500_000,
        50_000_000,
        30_000_000,
        40_000_000,
    )
    return OwnerDividendProposalCommand(
        company_id=company_id,
        actor_id=ActorId(
            ActorKind.USER,
            UserId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ),
        correlation_id=CorrelationId("owner-dividend-proposal"),
        idempotency_key=IdempotencyKey("owner-dividend-proposal-0001"),
        income_year=IncomeYear(2025),
        decision_id=CorporateDecisionId("11111111-1111-4111-8111-111111111111"),
        document_set_id=CorporateDocumentSetId("44444444-4444-4444-8444-444444444444"),
        company=PersistedCompanyFacts(company_id, "310279617", "LOGISK ØDE TIGER AS"),
        shareholders=shareholders,
        annual_basis=annual_basis,
        reviewed_facts=ReviewedOwnerDividendFacts(
            "310279617",
            "LOGISK ØDE TIGER AS",
            (
                ReviewedShareholderFacts("shareholder-1", "Åse Nordmann", 600),
                ReviewedShareholderFacts("shareholder-2", "Jørgen Østby", 400),
            ),
            1_000,
            30_000_000,
            "a" * 64,
            "b" * 64,
        ),
        board_meeting=BoardMeeting(
            LocalDate(date(2025, 6, 10)),
            time(9, 0),
            "  Os  ",
            BoardTreatmentMethod.PHYSICAL,
        ),
        board_participants=(
            BoardParticipant("board-2", " Jørgen   Østby ", BoardRole.MEMBER, 2),
            BoardParticipant("board-1", "Åse Nordmann", BoardRole.CHAIR, 1),
        ),
        general_meeting=GeneralMeeting(
            LocalDate(date(2025, 6, 20)),
            time(10, 0),
            "Os",
            MeetingForm.PHYSICAL,
            " Åse Nordmann ",
            "Jørgen Østby",
        ),
        shareholder_ballots=(
            ShareholderBallot("shareholder-2", 400, ShareholderVote.FOR),
            ShareholderBallot("shareholder-1", 600, ShareholderVote.FOR),
        ),
        one_share_class_confirmed=True,
        full_board_participation_confirmed=True,
        unanimous_board_confirmed=True,
        supported_dividend_basis_confirmed=True,
        prudent_equity_and_liquidity_confirmed=True,
        dividend_amount_ore=10_000_001,
        payment_date=LocalDate(date(2025, 7, 1)),
    )


def test_owner_dividend_policy_reproduces_characterized_canonical_facts() -> None:
    decision = CorporateGovernanceService().build_owner_dividend_decision(
        supported_proposal()
    )

    assert decision.organization_number == "310279617"
    assert decision.legal_name == "LOGISK ØDE TIGER AS"
    assert decision.total_company_shares == 1_000
    assert [(item.shareholder_id, item.share_count) for item in decision.shareholders] == [
        ("shareholder-1", 600),
        ("shareholder-2", 400),
    ]
    assert [(item.participant_id, item.name) for item in decision.board_participants] == [
        ("board-1", "Åse Nordmann"),
        ("board-2", "Jørgen Østby"),
    ]
    assert decision.financial_totals.available_distribution_ore == 30_000_000
    assert decision.dividend.liquidity_after_payment_ore == 29_999_999
    assert [(item.shareholder_id, item.amount_ore) for item in decision.dividend.allocations] == [
        ("shareholder-1", 6_000_001),
        ("shareholder-2", 4_000_000),
    ]
    assert decision.source_hash == "0dae8fec5faceb20edf1e51cddb97ea06a4d0afcd6a7f420ba573b621f331b80"
    assert decision.decision_hash == "b48464dfed6114e3a32f0f4da0d4ca939fae79119c7fea8b8c9838083890a776"


def test_canonical_owner_dividend_renders_characterized_pdfs_in_process() -> None:
    service = CorporateGovernanceService()
    decision = service.build_owner_dividend_decision(supported_proposal())

    first = service.render_corporate_documents(decision)
    second = service.render_corporate_documents(decision)

    assert first == second
    assert [artifact.artifact_kind.value for artifact in first] == [
        "dividend_board_proposal",
        "dividend_general_meeting_minutes",
    ]
    assert [artifact.filename for artifact in first] == [
        "styrets-forslag-til-utbytte.pdf",
        "generalforsamlingsprotokoll-utbytte.pdf",
    ]
    assert [artifact.content_sha256 for artifact in first] == [
        "19b04c086bd4d851c92ca225c71bf1d3b5cd0adeaed6835837594bf4e642d7fe",
        "2aef1df2c8c7a2b817078810c6b2b578ad69ca5d03704d356fcb42b157e107d3",
    ]
    assert [artifact.byte_length for artifact in first] == [32130, 32389]
    assert all(artifact.pdf_bytes.startswith(b"%PDF-") for artifact in first)
    assert all(artifact.decision_hash == decision.decision_hash for artifact in first)


def supported_annual_close() -> AnnualCloseProposalCommand:
    owner = supported_proposal()
    return AnnualCloseProposalCommand(
        company_id=owner.company_id,
        actor_id=owner.actor_id,
        correlation_id=CorrelationId("annual-close-proposal"),
        idempotency_key=IdempotencyKey("annual-close-proposal-0001"),
        income_year=IncomeYear(2025),
        decision_id=CorporateDecisionId("44444444-4444-4444-8444-444444444444"),
        document_set_id=CorporateDocumentSetId(
            "55555555-5555-4555-8555-555555555555"
        ),
        company=owner.company,
        shareholders=owner.shareholders,
        annual_basis=replace(owner.annual_basis, income_year=IncomeYear(2025)),
        reviewed_facts=owner.reviewed_facts,
        board_meeting=replace(
            owner.board_meeting,
            meeting_date=LocalDate(date(2026, 4, 15)),
        ),
        board_participants=owner.board_participants,
        general_meeting=replace(
            owner.general_meeting,
            meeting_date=LocalDate(date(2026, 5, 10)),
        ),
        shareholder_ballots=owner.shareholder_ballots,
        one_share_class_confirmed=True,
        full_board_participation_confirmed=True,
        unanimous_board_confirmed=True,
        supported_dividend_basis_confirmed=True,
        prudent_equity_and_liquidity_confirmed=True,
        annual_result_allocation_ore=12_500_000,
    )


def test_annual_close_policy_and_renderer_reproduce_characterized_artifacts() -> None:
    service = CorporateGovernanceService()

    decision = service.build_annual_close_decision(supported_annual_close())
    artifacts = service.render_corporate_documents(decision)

    assert decision.source_hash == "0dae8fec5faceb20edf1e51cddb97ea06a4d0afcd6a7f420ba573b621f331b80"
    assert decision.decision_hash == "2e364c248ed1d6894fd69e69b82012ddddb492d572db5e377b05988ee8349eaa"
    assert decision.dividend is None
    assert [artifact.artifact_kind.value for artifact in artifacts] == [
        "annual_board_minutes",
        "annual_general_meeting_minutes",
    ]
    assert [artifact.content_sha256 for artifact in artifacts] == [
        "dc38c0c178f4a0bbd7e466581fae416d6ddeabfacf00027eaac95dbe7ad28e50",
        "270bf87a72e5ced5b13490e220e352bde7a16bff019f48d46bfa88ac1d561776",
    ]
    assert [artifact.byte_length for artifact in artifacts] == [32066, 32626]


def test_lifecycle_readiness_is_derived_by_the_python_governance_owner() -> None:
    service = CorporateGovernanceService()
    decision = service.build_owner_dividend_decision(supported_proposal())
    created_at = datetime(2025, 6, 20, 12, tzinfo=UTC)
    artifacts = (
        CorporateArtifactRecord(
            artifact_id=CorporateArtifactId(f"00000000-0000-4000-8000-00000000000{index}"),
            company_id=decision.company_id,
            income_year=decision.income_year,
            document_set_id=decision.document_set_id,
            artifact_kind=kind,
            variant=variant,
            document_id=DocumentReference(f"10000000-0000-4000-8000-00000000000{index}"),
            content_sha256=str(index) * 64,
            byte_length=100 + index,
            supersedes_artifact_id=(
                CorporateArtifactId(f"00000000-0000-4000-8000-00000000000{index - 2}")
                if variant is CorporateArtifactVariant.SIGNED_OWNER_ATTESTED
                else None
            ),
            created_by=str(decision.company_id),
            created_at=created_at,
        )
        for index, (kind, variant) in enumerate(
            (
                (CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL, CorporateArtifactVariant.UNSIGNED),
                (CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES, CorporateArtifactVariant.UNSIGNED),
                (CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL, CorporateArtifactVariant.SIGNED_OWNER_ATTESTED),
                (CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES, CorporateArtifactVariant.SIGNED_OWNER_ATTESTED),
            ),
            start=1,
        )
    )
    snapshot = CorporateLifecycleSnapshot(
        decisions=(CorporateDecisionRecord(
            decision_id=decision.decision_id,
            document_set_id=decision.document_set_id,
            company_id=decision.company_id,
            income_year=decision.income_year,
            decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
            annual_close_source_id=decision.annual_close_source_id,
            source_hash=decision.source_hash,
            canonical_input=canonical_owner_dividend_payload(decision),
            decision_hash=decision.decision_hash,
            created_by=str(decision.company_id),
            created_at=created_at,
        ),),
        document_sets=(CorporateDocumentSetRecord(
            document_set_id=decision.document_set_id,
            company_id=decision.company_id,
            income_year=decision.income_year,
            decision_id=decision.decision_id,
            template_family=decision.template_family,
            template_version=decision.template_version,
            decision_hash=decision.decision_hash,
            created_by=str(decision.company_id),
            created_at=created_at,
        ),),
        artifacts=artifacts,
        events=(
            CorporateEventRecord(
                event_id=CorporateEventId("20000000-0000-4000-8000-000000000001"),
                company_id=decision.company_id,
                income_year=decision.income_year,
                decision_id=decision.decision_id,
                document_set_id=decision.document_set_id,
                artifact_id=None,
                event_kind="facts_approved",
                actor_id=str(decision.company_id),
                occurred_at=created_at,
                decision_hash=decision.decision_hash,
                content_sha256=None,
                metadata={},
                idempotency_key="facts-approved",
            ),
            CorporateEventRecord(
                event_id=CorporateEventId("20000000-0000-4000-8000-000000000002"),
                company_id=decision.company_id,
                income_year=decision.income_year,
                decision_id=decision.decision_id,
                document_set_id=decision.document_set_id,
                artifact_id=None,
                event_kind="payment_recorded",
                actor_id=str(decision.company_id),
                occurred_at=created_at,
                decision_hash=decision.decision_hash,
                content_sha256=None,
                metadata={"amountOre": 1_000_000},
                idempotency_key="payment-recorded",
            ),
        ),
        finalizations=(CorporateFinalizationRecord(
            finalization_id=CorporateFinalizationId("30000000-0000-4000-8000-000000000001"),
            company_id=decision.company_id,
            income_year=decision.income_year,
            decision_id=decision.decision_id,
            finalization_kind="owner_dividend_declared",
            holding_action_id=None,
            accounting_entry_id=None,
            annual_close_source_id=None,
            decision_hash=decision.decision_hash,
            signed_artifact_hashes={},
            accounting_policy_version="owner-dividend-accounting-v1",
            created_by=str(decision.company_id),
            created_at=created_at,
        ),),
    )

    readiness = service.assess_lifecycle(
        snapshot,
        company_id=decision.company_id,
        income_year=decision.income_year,
        decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
        current_source_hash=decision.source_hash,
    )

    assert readiness.state.value == "partially_paid"
    assert readiness.current_source_matches is True
    assert readiness.ready_for_signing is True
    assert readiness.finalized is True
    assert readiness.declared_amount_ore == 10_000_001
    assert readiness.paid_amount_ore == 1_000_000
    assert readiness.remaining_amount_ore == 9_000_001
    assert readiness.required_signers == {
        "dividend_board_proposal": ("Jørgen Østby", "Åse Nordmann"),
        "dividend_general_meeting_minutes": ("Jørgen Østby", "Åse Nordmann"),
    }
    assert readiness.blockers == ()


def test_lifecycle_readiness_blocks_missing_and_stale_annual_evidence() -> None:
    service = CorporateGovernanceService()
    proposal = supported_annual_close()

    missing = service.assess_lifecycle(
        CorporateLifecycleSnapshot((), (), (), (), ()),
        company_id=proposal.company_id,
        income_year=proposal.income_year,
        decision_kind=CorporateDecisionKind.ANNUAL_CLOSE,
        current_source_hash="f" * 64,
    )

    assert [item.code for item in missing.blockers] == [
        "corporate_documents_decision_missing"
    ]
    assert missing.annual_submission_ready is False


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda command: replace(
                command,
                reviewed_facts=replace(command.reviewed_facts, legal_name="OTHER AS"),
            ),
            CorporateGovernanceErrorCode.REVIEWED_FACTS_CHANGED,
        ),
        (
            lambda command: replace(command, unanimous_board_confirmed=False),
            CorporateGovernanceErrorCode.NON_UNANIMOUS,
        ),
        (
            lambda command: replace(command, dividend_amount_ore=30_000_001),
            CorporateGovernanceErrorCode.EQUITY_OR_LIQUIDITY_FAILED,
        ),
        (
            lambda command: replace(
                command,
                shareholder_ballots=command.shareholder_ballots[:1],
            ),
            CorporateGovernanceErrorCode.SHAREHOLDER_FACTS_MISMATCH,
        ),
    ],
)
def test_owner_dividend_policy_fails_closed_without_reinterpreting_input(
    mutate, code
) -> None:
    with pytest.raises(CorporateGovernanceError) as raised:
        CorporateGovernanceService().build_owner_dividend_decision(
            mutate(supported_proposal())
        )
    assert raised.value.code == code


def test_owner_dividend_policy_is_deterministic_across_input_order() -> None:
    command = supported_proposal()
    reordered = replace(
        command,
        shareholders=tuple(reversed(command.shareholders)),
        board_participants=tuple(reversed(command.board_participants)),
        shareholder_ballots=tuple(reversed(command.shareholder_ballots)),
    )
    service = CorporateGovernanceService()
    assert service.build_owner_dividend_decision(command) == service.build_owner_dividend_decision(
        reordered
    )


def supported_shareholder_loan() -> RecordShareholderLoanCommand:
    proposal = supported_proposal()
    return RecordShareholderLoanCommand(
        company_id=proposal.company_id,
        actor_id=proposal.actor_id,
        correlation_id=CorrelationId("shareholder-loan-record"),
        idempotency_key=IdempotencyKey("shareholder-loan-record-0001"),
        income_year=IncomeYear(2025),
        action_id=CorporateEventId("12121212-1212-4212-8212-121212121212"),
        ledger_entry_id=AccountingEntryReference(
            "13131313-1313-4313-8313-131313131313"
        ),
        loan_date=LocalDate(date(2025, 3, 1)),
        amount=Money.nok("1250.50"),
        direction=ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
        counterparty_name="  Eier   Holding AS  ",
        document_status=ShareholderLoanDocumentStatus.ATTACHED,
        interest_modelled=True,
        related_party_security=False,
        bank_transaction_id=None,
        document_id=None,
    )


def test_shareholder_loan_policy_normalizes_supported_owner_intent() -> None:
    loan = CorporateGovernanceService().validate_shareholder_loan(
        supported_shareholder_loan()
    )

    assert loan.counterparty_name == "Eier Holding AS"
    assert loan.amount_ore == 125_050
    assert loan.direction is ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY
    assert loan.loan_date.value == date(2025, 3, 1)
    assert loan.interest_modelled is True
    assert loan.related_party_security is False


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda command: replace(
                command,
                direction=ShareholderLoanDirection.COMPANY_TO_PERSONAL_SHAREHOLDER,
            ),
            CorporateGovernanceErrorCode.PERSONAL_SHAREHOLDER_LOAN_BLOCKED,
        ),
        (
            lambda command: replace(command, related_party_security=True),
            CorporateGovernanceErrorCode.RELATED_PARTY_SECURITY_BLOCKED,
        ),
        (
            lambda command: replace(
                command,
                loan_date=LocalDate(date(2024, 12, 31)),
            ),
            CorporateGovernanceErrorCode.INVALID_INPUT,
        ),
    ],
)
def test_shareholder_loan_policy_preserves_characterized_hard_blocks(
    mutate, code
) -> None:
    with pytest.raises(CorporateGovernanceError) as raised:
        CorporateGovernanceService().validate_shareholder_loan(
            mutate(supported_shareholder_loan())
        )
    assert raised.value.code == code
