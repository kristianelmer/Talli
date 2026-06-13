from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from holding_core.models import DividendEvent, FilingCase, FormationEvent


class ReadinessIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str
    code: str
    message: str


class ReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    status: str
    issues: list[ReadinessIssue]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


def assess_rf1086_readiness(case: FilingCase) -> ReadinessResult:
    issues: list[ReadinessIssue] = []

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
            if event.share_count_after != case.share_snapshot.current_share_count:
                issues.append(_warning("formation_share_count_check", "Stiftelseshendelse bør avstemmes mot utgående antall aksjer."))
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

