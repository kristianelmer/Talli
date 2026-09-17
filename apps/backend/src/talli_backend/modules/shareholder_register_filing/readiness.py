from __future__ import annotations

from .public import (
    Rf1086Case as FilingCase, Rf1086DividendEvent as DividendEvent,
    Rf1086FormationEvent as FormationEvent, Rf1086ReadinessIssue as ReadinessIssue,
    Rf1086ReadinessResult as ReadinessResult,
)


def assess_rf1086_readiness(case: FilingCase) -> ReadinessResult:
    issues: list[ReadinessIssue] = []
    try:
        validate_capital_case(case)
    except ValueError:
        return ReadinessResult(filing="aksjonærregisteroppgaven", status="blocked",
            issues=(_error("capital_event_reconciliation",
                "Aksjer, kapital og hendelser stemmer ikke overens. Kontroller tidspunkt, aksjonærfordeling og inngående og utgående verdier."),))

    if case.company.share_type != "01":
        issues.append(_error("unsupported_share_class", "Kun ordinær aksjeklasse er støttet i første versjon."))

    previous_total = sum(snapshot.previous_share_count for snapshot in case.shareholder_snapshots)
    current_total = sum(snapshot.current_share_count for snapshot in case.shareholder_snapshots)
    if previous_total != case.share_snapshot.previous_share_count:
        issues.append(
            _error(
                "previous_share_count_mismatch",
                "Sum aksjer 1. januar per aksjonær stemmer ikke med selskapets aksjer.",
            )
        )
    if current_total != case.share_snapshot.current_share_count:
        issues.append(
            _error(
                "current_share_count_mismatch",
                "Sum aksjer 31. desember per aksjonær stemmer ikke med selskapets aksjer.",
            )
        )

    for event in case.events:
        if isinstance(event, DividendEvent):
            allocated = sum(allocation.amount for allocation in event.allocations)
            if round(allocated, 2) != round(event.total_amount, 2):
                issues.append(_error("dividend_allocation_mismatch", "Sum utbytte per aksjonær stemmer ikke med selskapets utbytte."))
        if isinstance(event, FormationEvent):
            allocated = sum(allocation.share_count for allocation in event.allocations)
            if allocated != event.issued_share_count:
                issues.append(_error("formation_allocation_mismatch", "Stiftelsesallokeringer stemmer ikke med antall utstedte aksjer."))

    status = "blocked" if any(issue.level == "error" for issue in issues) else "ready"
    return ReadinessResult(filing="aksjonærregisteroppgaven", status=status, issues=issues)


def format_readiness_report(result: ReadinessResult) -> str:
    lines = [f"Filing readiness: {result.filing}", ""]
    lines.append("Status: klar for simulering" if result.is_ready else "Status: blokkert")

    errors = [issue for issue in result.issues if issue.level == "error"]
    warnings = [issue for issue in result.issues if issue.level == "warning"]
    if errors:
        lines.extend(["", "Blokkerende feil:"])
        lines.extend(f"- {issue.message}" for issue in errors)
    if warnings:
        lines.extend(["", "Advarsler:"])
        lines.extend(f"- {issue.message}" for issue in warnings)
    if not errors and not warnings:
        lines.extend(["", "Ingen kjente blokkerende feil eller advarsler i lanseringssubset."])
    return "\n".join(lines) + "\n"


def _error(code: str, message: str) -> ReadinessIssue:
    return ReadinessIssue(level="error", code=code, message=message)


def _warning(code: str, message: str) -> ReadinessIssue:
    return ReadinessIssue(level="warning", code=code, message=message)



CAPITAL_EVENT_TYPES = frozenset({"cash_issue", "cash_nominal_increase", "loss_covering_reduction"})


def validate_capital_case(case) -> None:
    try:
        _validate_capital_case(case)
    except (TypeError, AttributeError, ArithmeticError) as error:
        raise ValueError("capital case contains malformed values") from error


def _validate_capital_case(case) -> None:
    """Reconcile the complete chronology before admitting a capital-event case.

    Shared by private parsing and public-value readiness for every RF case.
    Monetary arithmetic uses decimal input values, never binary float tolerance.
    """
    from decimal import Decimal, InvalidOperation

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def money(value):
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("capital case amounts must be finite non-negative decimals") from None
        require(result.is_finite() and result >= 0, "capital case amounts must be finite non-negative decimals")
        require(result == result.quantize(Decimal("0.000001")), "capital case amounts support at most six decimal places")
        return result

    def count(value):
        require(type(value) is int and value >= 0, "capital case share counts must be non-negative integers")
        return value

    holders = {holder.id for holder in case.shareholders}
    require(bool(holders) and len(holders) == len(case.shareholders) and all(holders), "capital case shareholder ids must be unique and non-empty")
    snapshots = {snapshot.shareholder_id: snapshot for snapshot in case.shareholder_snapshots}
    require(len(snapshots) == len(case.shareholder_snapshots) and set(snapshots) == holders, "capital case snapshots must match unique shareholders")
    shares = case.share_snapshot
    holdings = {key: count(item.previous_share_count) for key, item in snapshots.items()}
    share_count = count(shares.previous_share_count)
    capital = money(shares.previous_share_capital)
    nominal = money(shares.previous_nominal_value)
    paid_in = money(shares.previous_paid_in_share_capital)
    premium = money(shares.previous_paid_in_premium)
    require(sum(holdings.values()) == share_count and capital == nominal * share_count, "capital case opening share capital and holdings must reconcile")
    last_timestamp = None
    loss_coverage_seen = False
    for event in case.events:
        require(event.timestamp.tzinfo is None and event.timestamp.microsecond == 0 and event.timestamp.year == case.company.income_year,
                "capital case timestamps must be local whole seconds in the income year")
        require(last_timestamp is None or event.timestamp > last_timestamp, "capital case events must have distinct ascending timestamps")
        last_timestamp = event.timestamp
        if event.type in CAPITAL_EVENT_TYPES:
            require(event.registration_confirmed is True, "capital changes require confirmed registration")
        if event.type in {"formation", "cash_issue"}:
            issued = count(event.issued_share_count)
            issue_nominal = money(event.nominal_value)
            issue_premium = money(event.premium)
            require(issued > 0 and issue_nominal > 0, "cash issuance requires positive shares and nominal value")
            if event.type == "formation":
                require(share_count == 0 and capital == paid_in == premium == 0, "formation requires an empty opening position")
                nominal = issue_nominal
            else:
                require(share_count > 0 and issue_nominal == nominal, "new cash shares must retain the existing nominal value")
            ids = [item.shareholder_id for item in event.allocations]
            require(len(ids) == len(set(ids)) and set(ids) <= holders, "cash issuance allocations require unique known shareholders")
            require(sum(count(item.share_count) for item in event.allocations) == issued, "cash issuance allocations must equal issued shares")
            for item in event.allocations:
                require(item.share_count > 0 and money(item.acquisition_value) == item.share_count * (nominal + issue_premium), "cash acquisition value must equal allocated nominal and premium")
                holdings[item.shareholder_id] += item.share_count
            share_count += issued
            require(count(event.share_count_after) == share_count, "cash issuance share count after must reconcile")
            capital += issued * nominal
            paid_in += issued * nominal
            premium += issued * issue_premium
        elif event.type == "cash_nominal_increase":
            delta = money(event.nominal_value_increase)
            amount = money(event.capital_increase)
            require(share_count > 0 and delta > 0 and amount == share_count * delta, "nominal increase must reconcile with outstanding shares")
            require(money(event.nominal_value_after) == nominal + delta, "nominal value after increase must reconcile")
            active = {key for key, value in holdings.items() if value > 0}
            ids = [item.shareholder_id for item in event.allocations]
            require(len(ids) == len(set(ids)) and set(ids) == active, "nominal increase requires every current shareholder exactly once")
            for item in event.allocations:
                require(count(item.share_count_basis) == holdings[item.shareholder_id] and money(item.capital_increase) == item.share_count_basis * delta,
                        "nominal increase allocation must reconcile with event-time holdings")
            require(sum(money(item.premium) for item in event.allocations) == money(event.premium), "nominal increase premium allocations must reconcile")
            nominal += delta
            capital += amount
            paid_in += amount
            premium += money(event.premium)
        elif event.type == "loss_covering_reduction":
            delta = money(event.nominal_value_reduction)
            amount = money(event.capital_reduction)
            require(type(event.fund_issued_capital_before) is int and event.fund_issued_capital_before == 0, "fund-issued capital is outside the supported loss-covering scope")
            require(paid_in >= capital, "loss cover requires evidence of fully paid-in registered capital")
            require(share_count > 0 and delta > 0 and amount == share_count * delta, "loss reduction must reconcile with outstanding shares")
            require(money(event.nominal_value_after) == nominal - delta and nominal - delta > 0, "loss reduction must retain a positive reconciled nominal value")
            nominal -= delta
            capital -= amount
            loss_coverage_seen = True
            # No shareholder repayment: tax paid-in capital and premium survive.
        elif event.type == "share_sale":
            require(event.seller_shareholder_id in holders and event.buyer_shareholder_id in holders and event.seller_shareholder_id != event.buyer_shareholder_id,
                    "share sale requires distinct known shareholders")
            quantity = count(event.share_count)
            require(quantity > 0 and holdings[event.seller_shareholder_id] >= quantity, "share sale exceeds event-time holdings")
            money(event.consideration)
            holdings[event.seller_shareholder_id] -= quantity
            holdings[event.buyer_shareholder_id] += quantity
        elif event.type == "dividend":
            # Registration alone does not establish creditor notice or an
            # exception to the three-year distribution restriction. The source
            # contract does not yet carry independently verified clearance.
            require(not loss_coverage_seen, "dividend after loss coverage requires verified distribution-restriction clearance")
            ids = [item.shareholder_id for item in event.allocations]
            active = {key for key, value in holdings.items() if value > 0}
            require(len(ids) == len(set(ids)) and set(ids) == active, "ordinary dividend requires every current shareholder exactly once")
            rate = money(event.per_share_amount)
            for item in event.allocations:
                require(count(item.share_count_basis) == holdings[item.shareholder_id] and money(item.amount) == rate * item.share_count_basis, "dividend allocation must reconcile with event-time holdings")
            require(money(event.total_amount) == rate * share_count, "dividend total must reconcile")
        else:
            raise ValueError("unsupported event in capital case")
        require(capital >= 30000, "supported Norwegian AS must retain at least NOK 30000 registered capital")
    require(share_count > 0 and capital >= 30000, "supported Norwegian AS requires shares and at least NOK 30000 registered capital")
    require(share_count == count(shares.current_share_count) and capital == money(shares.current_share_capital) and nominal == money(shares.current_nominal_value), "capital case closing registered capital must reconcile")
    require(paid_in == money(shares.current_paid_in_share_capital) and premium == money(shares.current_paid_in_premium), "capital case closing tax paid-in capital and premium must reconcile")
    require(all(holdings[key] == count(item.current_share_count) for key, item in snapshots.items()), "capital case closing shareholder holdings must reconcile")
