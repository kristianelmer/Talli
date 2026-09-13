from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from talli_backend.application.new_year_opening import (
    OpeningShareholderView,
    OpeningSnapshotCursor,
    OpeningSnapshotPage,
    OpeningSnapshotView,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    IncomeYear,
    Money,
    Timestamp,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
SETUP_ID = "60000000-0000-0000-0000-000000000006"
ACTOR = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000002"),
)


def opening_view() -> OpeningSnapshotView:
    return OpeningSnapshotView(
        setup_id=SETUP_ID,
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        bank_balance=Money.nok("9007199254740993.12"),
        share_capital=Money.nok("30000"),
        share_count=100,
        nominal_value=Money.nok("300"),
        locked_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
        created_at=Timestamp(datetime(2026, 8, 27, 9, tzinfo=UTC)),
        created_by=ACTOR,
        shareholders=(
            OpeningShareholderView(
                shareholder_id="70000000-0000-0000-0000-000000000007",
                setup_id=SETUP_ID,
                company_id=COMPANY_ID,
                name=" Owner ",
                shareholder_kind="norwegian_person",
                national_id="01010112345",
                org_number=None,
                share_count=100,
            ),
        ),
    )


def test_legacy_opening_projection_normalizes_and_preserves_exact_money() -> None:
    view = opening_view()

    assert view.bank_balance == Money.nok("9007199254740993.12")
    assert view.shareholders[0].name == "Owner"
    assert view.shareholders[0].shareholder_id == (
        "70000000-0000-0000-0000-000000000007"
    )


def test_legacy_opening_pages_own_a_bounded_opaque_cursor() -> None:
    cursor = OpeningSnapshotCursor("opaque-next")
    page = OpeningSnapshotPage(
        items=(opening_view(),),
        next_cursor=cursor,
        has_more=True,
    )

    assert page.next_cursor == cursor
    with pytest.raises(ValueError):
        OpeningSnapshotCursor("x" * 4097)
    with pytest.raises(ValueError):
        OpeningSnapshotPage(
            items=(opening_view(),),
            next_cursor=None,
            has_more=True,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda view: replace(view, share_count=99),
        lambda view: replace(view, share_capital=Money.nok("29999")),
        lambda view: replace(view, shareholders=()),
        lambda view: replace(
            view,
            shareholders=(
                replace(
                    view.shareholders[0],
                    company_id=CompanyId(
                        "10000000-0000-0000-0000-000000000099"
                    ),
                ),
            ),
        ),
        lambda view: replace(
            view,
            shareholders=(
                replace(view.shareholders[0], share_count=50),
                replace(view.shareholders[0], share_count=50),
            ),
        ),
        lambda view: replace(
            view,
            shareholders=(
                replace(
                    view.shareholders[0],
                    shareholder_kind="norwegian_company",
                ),
            ),
        ),
    ],
)
def test_legacy_opening_projection_fails_closed_on_inconsistent_facts(
    mutation,
) -> None:
    with pytest.raises(ValueError):
        mutation(opening_view())
