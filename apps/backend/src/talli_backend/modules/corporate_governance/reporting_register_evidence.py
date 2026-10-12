"""Additive reporting projection; legacy year selection and hashes stay frozen."""
from . import public as gov
from .register_evidence_amendment import _digest, _identity, _integer, _original_payload, _sha
from .reporting_year import _canonical
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

_CODEC = 'corporate-reporting-register-evidence-v1'
_PROJECTION = 'corporate-reporting-register-evidence-projection-v1'
_ELIGIBLE = {
    (gov.SupportedCorporateEventKind.CASH_CAPITAL_INCREASE, gov.SupportedCorporateEventPhase.REGISTERED),
    (gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION, gov.SupportedCorporateEventPhase.REGISTERED),
    (gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION, gov.SupportedCorporateEventPhase.FIRST_RECOGNIZED_AFTER_REGISTRATION),
}


def _require(value):
    if value is not True:
        raise gov.CorporateGovernanceError.unavailable()


def _scope(query):
    _require(type(query) is gov.CorporateReportingRegisterEvidenceQuery)
    _require(type(query.income_year) is IncomeYear)
    _require(type(query.actor_id) is ActorId and query.actor_id.kind is ActorKind.USER)
    _identity(query.actor_id.subject, UserId)
    return dict(company_id=_identity(query.company_id, CompanyId), income_year=_integer(query.income_year.value, 2000, 2100))


def _eligible(row):
    return row.correction_of_event_id is None and (row.event.event_kind, row.event.phase) in _ELIGIBLE


def _commitments(query, chains):
    _require(type(chains) is tuple)
    scope = _scope(query); descriptors = []; identities = []
    for snapshot in chains:
        _require(type(snapshot) is gov.CorporateRegisterEvidenceChainSnapshot)
        event = snapshot.chain.anchor.original.event
        expected = gov.CorporateRegisterEvidenceQuery(query.company_id, event.income_year, query.actor_id, event.event_id)
        gov.assert_corporate_register_evidence_chain_snapshot(snapshot, query=expected)
        _require(_eligible(snapshot.chain.anchor.original))
        identities.append(str(event.event_id))
        descriptors.append(dict(event_id=str(event.event_id), income_year=int(event.income_year),
            anchor_sha256=snapshot.chain.anchor.anchor_sha256, amendment_count=snapshot.amendment_count,
            enumeration_sha256=snapshot.enumeration_sha256))
    _require(identities == sorted(set(identities)))
    body = dict(**scope, chain_count=len(chains), chains=descriptors)
    return _digest([_CODEC, body])


def _projection_digest(query, original, chain_sha):
    return _digest([_PROJECTION, dict(**_scope(query),
        original_enumeration_sha256=original.enumeration_sha256, chain_enumeration_sha256=chain_sha)])


def _assert(value, query):
    _scope(query)
    _require(type(value) is gov.CorporateGovernanceYearRegisterEvidence and value.query == query)
    original = value.original
    _require(type(original) is gov.CorporateGovernanceYearEvidence
        and (original.company_id, original.income_year) == (query.company_id, query.income_year))
    # Recompute the old public view's existing hash without changing its codec.
    old_body = dict(version='corporate-reporting-year-2', company_id=original.company_id,
        income_year=original.income_year, dividends=original.dividends,
        supported_events=original.supported_events, ledger_amendments=original.ledger_amendments)
    _require(_sha(original.enumeration_sha256) == _digest(_canonical(old_body)))
    chain_sha = _commitments(query, value.register_chains)
    _require(_integer(value.chain_count, 0) == len(value.register_chains)
        and _sha(value.chain_enumeration_sha256) == chain_sha)
    _require(_sha(value.enumeration_sha256) == _projection_digest(query, original, chain_sha))
    # All eligible originals visible in the year view must match too. Complete
    # off-year coverage additionally needs the original company-wide basis below.
    indexed = {row.chain.anchor.original.event.event_id: row for row in value.register_chains}
    for item in original.supported_events:
        for row in (item.recorded, *item.lifecycle_events):
            if _eligible(row):
                _require(row.event.event_id in indexed)
                _require(_original_payload(row) == _original_payload(indexed[row.event.event_id].chain.anchor.original))


def assert_projection(value, *, query):
    try:
        _assert(value, query)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise gov.CorporateGovernanceError.unavailable() from None


def build(*, query, basis, amendments, register_chains):
    try:
        _scope(query)
        _require(type(basis) is gov.CorporateReportingYearBasis and basis.company_id == query.company_id)
        original = gov.build_reporting_year_evidence(basis=basis, income_year=query.income_year, amendments=amendments)
        expected = {row.event.event_id: row for row in basis.supported_events if _eligible(row)}
        _commitments(query, register_chains)
        _require(set(expected) == {row.chain.anchor.original.event.event_id for row in register_chains})
        for row in register_chains:
            # An eligible legacy row lacking RF facts fails here; it is not an
            # absent chain or a fabricated known-zero amendment history.
            _require(_original_payload(expected[row.chain.anchor.original.event.event_id]) == _original_payload(row.chain.anchor.original))
        chain_sha = _commitments(query, register_chains)
        value = gov.CorporateGovernanceYearRegisterEvidence(query, original, register_chains, len(register_chains),
            chain_sha, _projection_digest(query, original, chain_sha))
        _assert(value, query)
        return value
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise gov.CorporateGovernanceError.unavailable() from None
