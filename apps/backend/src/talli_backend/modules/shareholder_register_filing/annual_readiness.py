"""RF-owned annual prerequisites from complete guarded owner projections."""
import re
from uuid import UUID

from . import public as rf

FAMILIES = frozenset({'opening', 'ledger', 'banking', 'interview', 'documents'})
NOT_EVALUATED = ('current_review_comments', 'filing_overrides', 'authority_permission',
                 'billing_entitlement', 'technical_release', 'warning_acknowledgements')
DOCUMENT_STATUSES = frozenset({'staged', 'attached', 'quarantined', 'generated_unsigned',
    'signed_owner_attested', 'missing_accepted', 'missing_accepted_warning', 'not_required', 'stored'})


def _require(condition):
    if not condition:
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')


def _ids(values):
    _require(type(values) is tuple and all(type(value) is str and str(UUID(value)) == value for value in values)
             and len(set(values)) == len(values) and values == tuple(sorted(values)))


def _validate(inputs, source):
    _require(isinstance(inputs, rf.Rf1086AnnualReadinessInputs)
             and inputs.company_id == source.company_id and inputs.income_year == source.income_year)
    for values in (inputs.opening_snapshot_ids, inputs.opening_bank_snapshot_ids, inputs.period_lock_ids):
        _ids(values)
    _require(len(inputs.opening_snapshot_ids) <= 1)
    counts = inputs.bank_transaction_count, inputs.unmatched_bank_count, inputs.accepted_bank_warning_count
    _require(all(type(value) is int and value >= 0 for value in counts)
             and counts[1] + counts[2] <= counts[0])
    answers = inputs.bank_balance_confirmed, inputs.has_unpaid_items, inputs.authority_to_submit_confirmed
    if inputs.interview_source_id is None:
        _require(all(value is None for value in answers))
    else:
        _ids((inputs.interview_source_id,))
        _require(all(type(value) is bool for value in answers))
    _require(set(inputs.evidence_sha256) == FAMILIES
             and all(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None
                     for value in inputs.evidence_sha256.values()))
    _require(type(inputs.documents) is tuple)
    for item in inputs.documents:
        _require(isinstance(item, rf.Rf1086AnnualDocumentStatus) and type(item.linked_to) is str
                 and type(item.status) is str and item.status in DOCUMENT_STATUSES)
    _ids(tuple(item.document_id for item in inputs.documents))


def build(source, preview, inputs):
    try:
        source_proof = rf.build_rf1086_source_readiness(source, preview)
        _validate(inputs, source)
        issues = list(source_proof.issues)
        accepted = []
        def issue(level, code, message):
            issues.append(rf.Rf1086ReadinessIssue(level, code, message))
        if not inputs.opening_snapshot_ids:
            issue('error', 'opening_balance_missing', 'Åpningsbalanse må være låst for inntektsåret.')
        if inputs.opening_snapshot_ids != inputs.opening_bank_snapshot_ids or not inputs.opening_bank_snapshot_ids:
            issue('error', 'opening_bank_input_missing_or_mismatched', 'Bankgrunnlaget må tilhøre årets låste åpningsbalanse.')
        if not inputs.period_lock_ids:
            issue('warning', 'period_not_locked', 'Inntektsåret er ikke periode-låst.')
        if inputs.interview_source_id is None:
            issue('warning', 'annual_data_missing', 'Årsavslutningsintervjuet er ikke fullført.')
        else:
            if not inputs.bank_balance_confirmed:
                issue('warning', 'bank_balance_not_confirmed', 'Bankbalanse er ikke bekreftet i årsavslutningsintervjuet.')
            if inputs.has_unpaid_items:
                issue('error', 'unpaid_items_not_supported', 'Ubetalte poster er ikke støttet i enkel annual loop.')
            if not inputs.authority_to_submit_confirmed:
                issue('error', 'annual_authority_not_confirmed', 'Innsendingsrett er ikke bekreftet i årsavslutningsintervjuet.')
        if inputs.unmatched_bank_count:
            issue('error', 'unmatched_bank_transactions', 'Alle banktransaksjoner må matches eller aksepteres.')
        relevant = [item for item in inputs.documents if any(label in item.linked_to.lower()
                    for label in ('aksjonaerregisteroppgaven', 'aksjonærregisteroppgaven', 'rf-1086'))]
        if any(item.status.startswith('missing_accepted') for item in relevant):
            issue('warning', 'missing_documents_accepted', 'Dokumentmangel er akseptert som advarsel.')
            accepted.append('missing_documents_accepted')
        ordered = tuple(sorted(issues, key=lambda item: (item.code, item.level, item.message)))
        _require(len({item.code for item in ordered}) == len(ordered))
        accepted = tuple(sorted(accepted))
        warnings = tuple(sorted(item.code for item in ordered if item.level == 'warning' and item.code not in accepted))
        status = ('blocked' if source_proof.readiness_status == 'blocked' or any(item.level == 'error' for item in ordered)
                  else 'warning' if warnings else 'ready')
        content = dict(schema_version='rf1086-annual-readiness-v1', source=source_proof,
                       annual_inputs=inputs, readiness_status=status, issues=ordered,
                       accepted_warning_codes=accepted, required_warning_codes=warnings, not_evaluated=NOT_EVALUATED)
        return rf.Rf1086AnnualReadinessProof(**content, proof_sha256=rf.rf1086_year_source_digest(content))
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable') from None


def assert_matches(proof, source, preview, inputs):
    expected = build(source, preview, inputs)
    if (not isinstance(proof, rf.Rf1086AnnualReadinessProof)
            or rf.rf1086_year_source_digest(proof) != rf.rf1086_year_source_digest(expected)):
        raise rf.Rf1086YearSourceError('rf1086_annual_readiness_mismatch')
