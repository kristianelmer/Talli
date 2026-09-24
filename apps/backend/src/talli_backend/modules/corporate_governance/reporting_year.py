"""Coherent owner evidence for dividend decision years and capital events.

Reporting-year selection uses a general-meeting decision's civil date. Receipt
persistence timestamps, dividend payment dates and annual-basis years are not
substitutes. The application supplies complete company-scoped Ledger amendments
read inside the same transaction as the Governance basis.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from decimal import Decimal, InvalidOperation
import hashlib
import json

from .public import (
    CorporateDecisionKind, CorporateGovernanceError, CorporateGovernanceYearEvidence,
    CorporateYearDividendEvidence, CorporateYearSupportedEvidence, SupportedCorporateEventKind,
    SupportedCorporateEventPhase,
)
from talli_backend.shared.kernel import LocalDate


def _require(value):
    if not value:
        raise CorporateGovernanceError.unavailable()


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _distinct(rows, key):
    result = {key(row): row for row in rows}
    _require(len(result) == len(rows))
    return result


_CASH_PHASES = (
    SupportedCorporateEventPhase.BINDING_SUBSCRIPTION,
    SupportedCorporateEventPhase.RESTRICTED_PAYMENT,
    SupportedCorporateEventPhase.REGISTERED,
)


def _cash_terms(row):
    facts = row.event.canonical_facts['businessFacts']
    amounts = []
    for name in ('nominal_increase', 'share_premium'):
        money = facts[name]
        _require(isinstance(money, Mapping) and money.get('currency') == 'NOK'
                 and isinstance(money.get('amount'), str))
        amount = Decimal(money['amount'])
        _require(amount.is_finite() and (amount > 0 if name == 'nominal_increase' else amount >= 0))
        amounts.append(amount)
    count = facts['issued_share_count']
    _require(type(count) is int and count > 0)
    return (*amounts, count)


def _amendment_status(rows, amendments):
    linked = [amendments[row.accounting_entry_id] for row in rows if row.accounting_entry_id in amendments]
    if any(row.correction_of_event_id is not None for row in rows) or any(row.replacement_entry_id is not None for row in linked):
        return 'corrected'
    if linked:
        return 'reversed'
    return None


def _cash_lifecycle(rows, income_year, amendments):
    # Governance's explicit reference is also Ledger's capital-increase key.
    # Amounts and dates validate this correlation; they never establish it.
    rows = tuple(sorted(rows, key=lambda row: (
        _CASH_PHASES.index(row.event.phase) if row.event.phase in _CASH_PHASES else len(_CASH_PHASES),
        row.event.event_date.value, str(row.event.event_id))))
    registered = [row for row in rows if row.event.phase is SupportedCorporateEventPhase.REGISTERED]
    representative = registered[0] if registered else rows[-1]
    status = _amendment_status(rows, amendments)
    if status is None:
        phases = [row.event.phase for row in rows]
        if (any(row.event.event_kind is not SupportedCorporateEventKind.CASH_CAPITAL_INCREASE for row in rows)
                or len(set(phases)) != len(phases) or any(phase not in _CASH_PHASES for phase in phases)):
            status = 'conflicting'
        elif not registered:
            status = 'incomplete'
        elif len(rows) == 1:
            # Preserve the existing registered-only receipt contract.
            status = 'recorded' if representative.event.income_year == income_year else 'incomplete'
        else:
            # A successful owned registration requires Ledger's subscription
            # and payment prerequisites. Either can come from an accepted
            # opening component, so absent Governance rows do not prove absent
            # Ledger anchors. Validate every available original against that
            # registered receipt; never synthesize an opening event.
            registration = registered[0]
            terms = [_cash_terms(row) for row in rows]
            dates = [row.event.event_date.value for row in rows]
            recorded_dates = [row.recorded_at for row in rows]
            coherent = (
                len({row.accounting_entry_id for row in rows}) == len(rows)
                and len({row.event.policy_version for row in rows}) == 1
                and all(term == terms[0] for term in terms)
                and dates == sorted(dates)
                and recorded_dates == sorted(recorded_dates)
            )
            payment = next((row for row in rows if row.event.phase is SupportedCorporateEventPhase.RESTRICTED_PAYMENT), None)
            if payment is not None:
                bank = payment.event.canonical_facts.get('bankFact')
                bank_reference = bank.get('transaction_id') if isinstance(bank, Mapping) else None
                if isinstance(bank_reference, Mapping):
                    bank_reference = bank_reference.get('value')
                coherent = coherent and (
                    payment.bank_transaction_id is not None
                    and payment.bank_transaction_id == registration.bank_transaction_id
                    and isinstance(bank, Mapping)
                    and bank_reference == str(payment.bank_transaction_id)
                    and bank == registration.event.canonical_facts.get('bankFact')
                )
            status = 'conflicting' if not coherent else (
                'recorded' if registration.event.income_year == income_year else 'incomplete')
    return CorporateYearSupportedEvidence(representative, status, rows)


def build_reporting_year_evidence(*, basis, income_year, amendments):
    try:
        return _build(basis, income_year, amendments)
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation):
        raise CorporateGovernanceError.unavailable() from None


def _build(basis, income_year, amendments):
    life = basis.lifecycle
    for rows in (life.decisions, life.document_sets, life.artifacts, life.events, life.finalizations, amendments):
        _require(all(row.company_id == basis.company_id for row in rows))
    _require(all(row.event.company_id == basis.company_id for row in basis.supported_events))
    decisions = _distinct(life.decisions, lambda row: row.decision_id)
    _distinct(life.document_sets, lambda row: row.document_set_id)
    _distinct(life.artifacts, lambda row: row.artifact_id)
    _distinct(life.events, lambda row: row.event_id)
    _distinct(life.finalizations, lambda row: row.finalization_id)
    supported = _distinct(basis.supported_events, lambda row: row.event.event_id)
    amendment_map = _distinct(amendments, lambda row: row.original_entry_id)
    _distinct(amendments, lambda row: row.reversal_entry_id)
    for row in amendments:
        _require(row.original_entry_id != row.reversal_entry_id and bool(row.reason.strip()))
        _require(row.replacement_entry_id not in (row.original_entry_id, row.reversal_entry_id))
        seen = set()
        cursor = row
        while cursor is not None:
            _require(cursor.original_entry_id not in seen)
            seen.add(cursor.original_entry_id)
            cursor = amendment_map.get(cursor.replacement_entry_id)
    for row in life.events + life.finalizations:
        _require(row.decision_id in decisions and row.decision_hash == decisions[row.decision_id].decision_hash)
    dividend_dates = {}
    for row in life.decisions:
        if row.decision_kind is not CorporateDecisionKind.OWNER_DIVIDEND:
            continue
        meeting = row.canonical_input.get('generalMeeting', row.canonical_input.get('general_meeting'))
        _require(isinstance(meeting, Mapping))
        raw = meeting.get('meetingDate', meeting.get('meeting_date'))
        _require(isinstance(raw, str))
        parsed = date.fromisoformat(raw)
        _require(parsed.isoformat() == raw)
        dividend_dates[row.decision_id] = parsed
    selected_decisions = {key for key, day in dividend_dates.items() if day.year == int(income_year)}
    # Preserve every correction connected to a selected decision, even when its
    # new decision date is in another reporting year. Never hide supersession.
    while True:
        related = {row.decision_id for row in life.decisions if row.decision_kind is CorporateDecisionKind.OWNER_DIVIDEND
                   and (row.supersedes_decision_id in selected_decisions or row.decision_id in selected_decisions)}
        related |= {decisions[key].supersedes_decision_id for key in selected_decisions
                    if decisions[key].supersedes_decision_id is not None}
        if related <= selected_decisions:
            break
        _require(related <= dividend_dates.keys())
        selected_decisions |= related
    for key in selected_decisions:
        seen = set()
        while key is not None:
            _require(key not in seen and key in decisions)
            seen.add(key)
            key = decisions[key].supersedes_decision_id
    dividends = []
    for key in sorted(selected_decisions, key=str):
        decision = decisions[key]
        sets = tuple(sorted((row for row in life.document_sets if row.decision_id == key), key=lambda row: str(row.document_set_id)))
        set_ids = {row.document_set_id for row in sets}
        artifacts = tuple(sorted((row for row in life.artifacts if row.document_set_id in set_ids), key=lambda row: str(row.artifact_id)))
        events = tuple(sorted((row for row in life.events if row.decision_id == key), key=lambda row: (row.occurred_at, str(row.event_id))))
        finals = tuple(sorted((row for row in life.finalizations if row.decision_id == key), key=lambda row: str(row.finalization_id)))
        _require(len(finals) <= 1)
        kinds = {row.event_kind for row in events}
        replaced = any(row.supersedes_decision_id == key for row in life.decisions)
        status = 'rejected' if 'rejected' in kinds else 'superseded' if replaced or 'superseded' in kinds else 'finalized' if finals else 'pending'
        dividends.append(CorporateYearDividendEvidence(decision, LocalDate(dividend_dates[key]), status, sets, artifacts, events, finals))
    capital_kinds = {SupportedCorporateEventKind.CASH_CAPITAL_INCREASE, SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION}
    selected_events = {key for key, row in supported.items() if row.event.event_kind in capital_kinds
                       and row.event.event_date.value.year == int(income_year)}
    while True:
        references = {supported[key].event.event_reference for key in selected_events
                      if supported[key].event.event_kind is SupportedCorporateEventKind.CASH_CAPITAL_INCREASE}
        related = {key for key, row in supported.items() if row.correction_of_event_id in selected_events
                   or row.event.event_reference in references}
        related |= {supported[key].correction_of_event_id for key in selected_events if supported[key].correction_of_event_id is not None}
        if related <= selected_events:
            break
        _require(related <= supported.keys())
        selected_events |= related
    for key in selected_events:
        seen = set()
        while key is not None:
            _require(key not in seen and key in supported)
            seen.add(key)
            key = supported[key].correction_of_event_id
    entries = {supported[key].accounting_entry_id for key in selected_events}
    entries |= {row.accounting_entry_id for item in dividends for row in item.finalizations if row.accounting_entry_id is not None}
    relevant = {}
    while True:
        found = [row for row in amendments if {row.original_entry_id, row.reversal_entry_id, row.replacement_entry_id} & entries]
        if len(found) == len(relevant):
            break
        relevant = {row.original_entry_id: row for row in found}
        entries |= {key for row in found for key in (row.original_entry_id, row.reversal_entry_id, row.replacement_entry_id) if key is not None}
    capital = []
    consumed = set()
    for key in sorted(selected_events, key=str):
        if key in consumed:
            continue
        row = supported[key]
        same_reference = [supported[item] for item in selected_events
                          if supported[item].event.event_reference == row.event.event_reference]
        if any(item.event.event_kind is SupportedCorporateEventKind.CASH_CAPITAL_INCREASE for item in same_reference):
            capital.append(_cash_lifecycle(same_reference, income_year, relevant))
            consumed.update(item.event.event_id for item in same_reference)
        else:
            capital.append(CorporateYearSupportedEvidence(row, _amendment_status((row,), relevant) or 'recorded'))
            consumed.add(key)
    capital.sort(key=lambda item: str(item.recorded.event.event_id))
    retained = tuple(sorted(relevant.values(), key=lambda row: str(row.original_entry_id)))
    payload = {'version': 'corporate-reporting-year-2', 'company_id': basis.company_id, 'income_year': income_year,
               'dividends': tuple(dividends), 'supported_events': tuple(capital), 'ledger_amendments': retained}
    digest = hashlib.sha256(json.dumps(_canonical(payload), ensure_ascii=False, allow_nan=False,
                                      sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return CorporateGovernanceYearEvidence(basis.company_id, income_year, tuple(dividends), tuple(capital), retained, digest)
