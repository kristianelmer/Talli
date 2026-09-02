from __future__ import annotations

from dataclasses import replace
from datetime import date, time

import pytest

from talli_backend.modules.corporate_governance.public import (
    ApprovedAnnualBasis,
    BoardMeeting,
    BoardParticipant,
    BoardRole,
    BoardTreatmentMethod,
    CorporateDecisionId,
    CorporateDocumentSetId,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateSourceReference,
    GeneralMeeting,
    MeetingForm,
    OwnerDividendProposalCommand,
    PersistedCompanyFacts,
    PersistedShareholderFacts,
    ReviewedOwnerDividendFacts,
    ReviewedShareholderFacts,
    ShareholderBallot,
    ShareholderVote,
)
from talli_backend.modules.corporate_governance.service import (
    CorporateGovernanceService,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
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
