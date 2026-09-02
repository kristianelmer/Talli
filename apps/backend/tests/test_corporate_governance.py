from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest
from talli_backend.application.annual_data_compatibility import (
    project_legacy_annual_basis,
)
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference,
    AnnualCloseEventKind,
    AnnualCloseProposalCommand,
    AnnualDataSourceFacts,
    BoardMeeting,
    BoardParticipant,
    BoardRole,
    BoardTreatmentMethod,
    CorporateAccountMovementFacts,
    CorporateArtifactId,
    CorporateArtifactKind,
    CorporateArtifactRecord,
    CorporateArtifactVariant,
    CorporateDecisionFactSources,
    CorporateDecisionId,
    CorporateDecisionKind,
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
    OwnerDividendEventKind,
    PersistedCompanyFacts,
    PersistedShareholderFacts,
    PreparedOwnerDividendFinalization,
    RecordAnnualCloseEventCommand,
    RecordOwnerDividendEventCommand,
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


def supported_fact_sources(annual_year: int = 2024) -> CorporateDecisionFactSources:
    company_id = CompanyId("22222222-2222-4222-8222-222222222222")
    shareholders = (
        PersistedShareholderFacts("shareholder-2", "Jørgen Østby", 400, 2),
        PersistedShareholderFacts("shareholder-1", "Åse Nordmann", 600, 1),
    )
    return CorporateDecisionFactSources(
        company=PersistedCompanyFacts(
            company_id,
            "310279617",
            "LOGISK ØDE TIGER AS",
        ),
        shareholders=shareholders,
        annual_data=(
            AnnualDataSourceFacts(
                CorporateSourceReference(
                    "33333333-3333-4333-8333-333333333333"
                ),
                company_id,
                IncomeYear(annual_year),
                {"general_meeting_approved": True},
                (),
                False,
                0,
                f"{annual_year + 1}-05-01T10:00:00+00:00",
                f"{annual_year + 1}-05-01T10:00:00+00:00",
            ),
        ),
    )


def supported_ledger_lines(annual_year: int = 2024) -> tuple[CorporateAccountMovementFacts, ...]:
    return (
        CorporateAccountMovementFacts(IncomeYear(annual_year), "8070", 0, 12_500_000),
        CorporateAccountMovementFacts(IncomeYear(annual_year), "2000", 0, 20_000_000),
        CorporateAccountMovementFacts(IncomeYear(annual_year), "2050", 0, 17_500_000),
        CorporateAccountMovementFacts(IncomeYear(annual_year), "1920", 40_000_000, 0),
    )


def test_annual_source_answers_are_deeply_immutable() -> None:
    source = supported_fact_sources().annual_data[0]

    with pytest.raises(TypeError):
        source.answers["general_meeting_approved"] = False  # type: ignore[index]


def test_prepared_finalization_artifact_hashes_are_immutable() -> None:
    prepared = PreparedOwnerDividendFinalization(
        declared_amount_ore=10_000,
        accounting_policy_version="owner-dividend-accounting-v1",
        declaration_debit_account="2050",
        dividend_payable_account="2920",
        signed_artifact_hashes={"minutes": "a" * 64},
        replay=None,
    )

    with pytest.raises(TypeError):
        prepared.signed_artifact_hashes["minutes"] = "b" * 64  # type: ignore[index]


def test_lifecycle_event_command_metadata_is_immutable() -> None:
    proposal = supported_proposal()
    shared = {
        "company_id": proposal.company_id,
        "actor_id": proposal.actor_id,
        "correlation_id": CorrelationId("immutable-event-metadata"),
        "decision_id": proposal.decision_id,
        "document_set_id": proposal.document_set_id,
        "decision_hash": "a" * 64,
        "metadata": {"reason": "owner-requested"},
    }
    commands = (
        RecordOwnerDividendEventCommand(
            **shared,
            idempotency_key=IdempotencyKey("immutable-owner-event-0001"),
            event_id=CorporateEventId("34343434-3434-4343-8343-343434343434"),
            event_kind=OwnerDividendEventKind.SUPERSEDED,
        ),
        RecordAnnualCloseEventCommand(
            **shared,
            idempotency_key=IdempotencyKey("immutable-annual-event-0001"),
            event_id=CorporateEventId("45454545-4545-4454-8454-454545454545"),
            event_kind=AnnualCloseEventKind.SUPERSEDED,
        ),
    )

    for command in commands:
        with pytest.raises(TypeError):
            command.metadata["reason"] = "changed"  # type: ignore[index]


def supported_proposal() -> OwnerDividendProposalCommand:
    company_id = CompanyId("22222222-2222-4222-8222-222222222222")
    facts = CorporateGovernanceService().derive_decision_facts(
        sources=supported_fact_sources(),
        ledger_lines=supported_ledger_lines(),
        decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
        income_year=IncomeYear(2025),
        annual_basis_projector=project_legacy_annual_basis,
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
        company=facts.company,
        shareholders=facts.shareholders,
        annual_basis=facts.annual_basis,
        reviewed_facts=facts.reviewed_facts,
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
    assert decision.source_hash == "5ad9e8951d1c3766dcf33b0cb59bb5dcdaa4fa09e66572199185ef37d3f98f4e"
    assert decision.decision_hash == "b5dad184686052b9e97cea1f2ac175f08a4e081068b14b87020c329669e7c621"


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
        "9c05041cf7d5d2258f39bb30768bda8f3bae58075e9071924bcae3dcb9ddd9b6",
        "63bf6a86aa13f76f336ac7f086bc85dc20b1e0cbf20f583cc7d203ddb0954e7e",
    ]
    assert [artifact.byte_length for artifact in first] == [32132, 32390]
    assert all(artifact.pdf_bytes.startswith(b"%PDF-") for artifact in first)
    assert all(artifact.decision_hash == decision.decision_hash for artifact in first)


def supported_annual_close() -> AnnualCloseProposalCommand:
    owner = supported_proposal()
    facts = CorporateGovernanceService().derive_decision_facts(
        sources=supported_fact_sources(2025),
        ledger_lines=supported_ledger_lines(2025),
        decision_kind=CorporateDecisionKind.ANNUAL_CLOSE,
        income_year=IncomeYear(2025),
        annual_basis_projector=project_legacy_annual_basis,
    )
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
        company=facts.company,
        shareholders=facts.shareholders,
        annual_basis=facts.annual_basis,
        reviewed_facts=facts.reviewed_facts,
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

    assert decision.source_hash == "a0f779b57f3da5dd2b2b4c1984cf47a2e225ce4ac84640b574ffa4ae5d68ce05"
    assert decision.decision_hash == "5765d1948383a6fb27c4c08cf1607cc4c5dca5cd8e95d6f004db77e446ec5c0a"
    assert decision.dividend is None
    assert [artifact.artifact_kind.value for artifact in artifacts] == [
        "annual_board_minutes",
        "annual_general_meeting_minutes",
    ]
    assert [artifact.content_sha256 for artifact in artifacts] == [
        "9dcb67fb0d822a72f0bc3946e0c41995a2d5479096630fed7c0a9b798d746544",
        "901228e7a88e53579fad2d15d825244a56ef8b223ef2bfa4154755b883bd4c30",
    ]
    assert [artifact.byte_length for artifact in artifacts] == [32069, 32628]


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
            supersedes_decision_id=None,
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
            supersedes_document_set_id=None,
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
                created_at=created_at,
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
                created_at=created_at,
                decision_hash=decision.decision_hash,
                content_sha256=None,
                metadata={"amountOre": 1_000_000, "proof": {"status": "recorded"}},
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

    with pytest.raises(TypeError):
        snapshot.decisions[0].canonical_input["financial_totals"]["cash_ore"] = 0  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.events[1].metadata["proof"]["status"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.finalizations[0].signed_artifact_hashes["changed"] = "0" * 64  # type: ignore[index]
    with pytest.raises(TypeError):
        readiness.generated_artifact_hashes["changed"] = "0" * 64  # type: ignore[index]
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

    superseded = service.assess_lifecycle(
        replace(
            snapshot,
            events=snapshot.events
            + (
                CorporateEventRecord(
                    event_id=CorporateEventId(
                        "20000000-0000-4000-8000-000000000003"
                    ),
                    company_id=decision.company_id,
                    income_year=decision.income_year,
                    decision_id=decision.decision_id,
                    document_set_id=decision.document_set_id,
                    artifact_id=None,
                    event_kind="superseded",
                    actor_id=str(decision.company_id),
                    occurred_at=created_at,
                    created_at=created_at,
                    decision_hash=decision.decision_hash,
                    content_sha256=None,
                    metadata={},
                    idempotency_key="superseded-decision",
                ),
            ),
        ),
        company_id=decision.company_id,
        income_year=decision.income_year,
        decision_kind=CorporateDecisionKind.OWNER_DIVIDEND,
        current_source_hash=decision.source_hash,
    )

    assert superseded.state.value == "superseded"
    assert superseded.ready_for_signing is False
    assert superseded.finalized is False
    assert "corporate_documents_terminal_decision" in {
        item.code for item in superseded.blockers
    }


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
