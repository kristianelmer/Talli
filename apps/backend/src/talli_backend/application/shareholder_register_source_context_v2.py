"""Construct v2 context from public owner evidence; no live writer is enabled.

Verified Documents projections are inputs, not original-byte proof. A future
capture/admission must obtain bytes outside guards and rerun this builder using
complete owner reads on its held connection before producing the SQL proof.
"""
from dataclasses import fields

from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.application.shareholder_register_source_workflow import (
    _capital_economics, _dividend_receipts, _reference, _require,
)


_KINDS = {
    gov.SupportedCorporateEventKind.CASH_CAPITAL_INCREASE: "cash_issue",
    gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION: "loss_covering_reduction",
}
_PHASES = {
    gov.SupportedCorporateEventPhase.REGISTERED,
    gov.SupportedCorporateEventPhase.FIRST_RECOGNIZED_AFTER_REGISTRATION,
}


def _fact(value):
    return rf.Rf1086YearRegisterFactV2(rf.Rf1086RegisterObservationId(value.record_id.value),
        value.revision, value.fact_sha256)


def _head(value):
    return None if value is None else rf.Rf1086YearGovernanceHeadV2(
        value.amendment_id.value, value.revision, value.amendment_sha256)


def _projection(view):
    chains = []
    for snapshot in view.register_chains:
        chain = snapshot.chain
        original = chain.anchor.original
        reference = original.event.canonical_facts["shareholderRegisterFact"]
        links = tuple(rf.Rf1086YearGovernanceLinkV2(_head(row.head), _head(row.command.expected_head),
            row.command.withdrawal.withdrawal_id.value, row.command.withdrawal.withdrawal_sha256,
            _fact(row.command.withdrawal.target), _fact(row.command.replacement), row.recorded_at)
            for row in chain.amendments)
        chains.append(rf.Rf1086YearGovernanceChainV2(original.event.event_id.value,
            original.event.company_id, original.event.income_year, _KINDS[original.event.event_kind],
            original.finalization_sha256, chain.anchor.anchor_sha256, chain.anchor.original_recorded_at,
            rf.Rf1086YearRegisterFactV2(rf.Rf1086RegisterObservationId(_reference(reference["record_id"])),
                reference["revision"], reference["fact_sha256"]),
            links, snapshot.amendment_count, snapshot.enumeration_sha256, _head(chain.head),
            _fact(chain.effective_register_fact),
            links[-1].recorded_at if links else chain.anchor.original_recorded_at))
    return rf.Rf1086YearGovernanceProjectionV2(view.query.company_id, view.query.income_year,
        view.original.enumeration_sha256, view.chain_enumeration_sha256, view.enumeration_sha256,
        tuple(chains), view.chain_count)


def _original_documents(recorded, chain, documents, company_id):
    hashes = []
    for fact in recorded.event.canonical_facts["documentFacts"]:
        document = documents.get(_reference(fact["document_id"]))
        _require(document is not None and document.company_id == company_id
            and document.content_sha256 == fact["content_sha256"],
            "rf1086_source_governance_signed_document_unverified")
        hashes.append(document.content_sha256)
    _require(bool(hashes), "rf1086_source_governance_signed_document_unverified")
    for receipt in chain.amendments:
        # Every receipt contains the original/memo/replacement union, including
        # intermediate replacements. Semantic revisions are not Documents versions.
        for expected in receipt.originals:
            document = documents.get(expected.document_id.value)
            _require(document is not None and document.company_id == expected.company_id == company_id
                and document.source_income_year == expected.source_income_year
                and document.metadata_sha256 == expected.metadata_sha256
                and document.content_sha256 == expected.content_sha256
                and document.byte_length == expected.byte_length,
                "rf1086_source_register_original_changed")
    return tuple(sorted(hashes))


async def build_verified_source_context_v2(session, command, company, identity_sha256, documents, view):
    """Use the supplied current RF read scope; never manufacture missing history."""
    _require(type(command) is rf.RecordRf1086YearSource and session.actor_id == command.actor_id,
        "rf1086_source_owner_required")
    _require(company == command.case.company, "rf1086_source_company_year_mismatch")
    _require(type(documents) is tuple and documents == command.documents
        and all(type(item) is rf.Rf1086YearDocumentEvidence and item.company_id == command.company_id
            for item in documents)
        and len({item.document_id for item in documents}) == len(documents),
        "rf1086_source_documents_unverified")
    query = gov.CorporateReportingRegisterEvidenceQuery(command.company_id, command.income_year, session.actor_id)
    try:
        gov.assert_reporting_year_register_evidence(view, query=query)
        projection = _projection(view)
    except (gov.CorporateGovernanceError, ValueError, TypeError, KeyError, AttributeError):
        raise rf.Rf1086YearSourceError("rf1086_source_governance_receipt_invalid") from None
    originals = view.original
    receipts = [rf.Rf1086YearGovernanceReceiptV2(item, None)
        for item in _dividend_receipts(originals, documents)]
    by_document = {item.document_id: item for item in documents}
    evidence = {item.governance_receipt_id: item for item in command.event_evidence
        if item.governance_receipt_id is not None}
    _require(len(evidence) == sum(item.governance_receipt_id is not None for item in command.event_evidence),
        "rf1086_source_governance_receipt_invalid")
    chains = {item.chain.anchor.original.event.event_id.value: item
        for item in view.register_chains if item.query.income_year == command.income_year}
    compact = {item.receipt_id: item for item in projection.chains}
    capital_ids = set()
    for item in originals.supported_events:
        recorded = item.recorded
        original = recorded.event
        kind = _KINDS.get(original.event_kind)
        _require(item.status == "recorded" and recorded.correction_of_event_id is None
            and original.phase in _PHASES and kind is not None,
            "rf1086_source_governance_unresolved")
        receipt_id = original.event_id.value
        selected = evidence.get(receipt_id)
        snapshot = chains.get(receipt_id)
        _require(selected is not None and snapshot is not None
            and 0 <= selected.event_index < len(command.case.events),
            "rf1086_source_governance_events_omitted")
        event = command.case.events[selected.event_index]
        _require(event.type == kind and original.company_id == command.company_id
            and original.income_year == command.income_year and original.event_date.value == event.timestamp.date(),
            "rf1086_source_governance_receipt_invalid")
        economic_sha = rf.rf1086_year_source_digest(_capital_economics(original, kind))
        _require(economic_sha == rf.rf1086_year_source_digest(rf.rf1086_governance_economic_facts(event)),
            "rf1086_source_governance_receipt_mismatch")
        chain = snapshot.chain
        signed_hashes = _original_documents(recorded, chain, by_document, command.company_id)
        current = chain.effective_register_fact
        observation_id = rf.Rf1086RegisterObservationId(current.record_id.value)
        observation = await session.read_current_register_observation(
            rf.Rf1086SourceQuery(command.company_id, command.income_year, session.actor_id), observation_id)
        _require(observation is not None, "rf1086_source_independent_register_unavailable")
        before, after = rf.rf1086_event_register_states(command.case, selected.event_index)
        rf.verify_rf1086_register_observation(observation, rf.Rf1086RegisterObservationMatchQuery(
            observation_id, current.revision, current.fact_sha256, command.company_id,
            command.income_year, event.timestamp, event.type, before, after))
        _require(observation.confirmed_at <= compact[receipt_id].evidence_cutoff,
            "rf1086_source_register_postdates_governance")
        for expected in observation.command.documents:
            document = by_document.get(expected.document_id)
            _require(document is not None and all(getattr(document, field.name) == getattr(expected, field.name)
                for field in fields(rf.Rf1086YearDocumentEvidence)),
                "rf1086_source_register_original_changed")
        reference = original.canonical_facts["shareholderRegisterFact"]
        receipt = rf.Rf1086YearGovernanceReceipt(receipt_id, command.company_id, command.income_year,
            kind, economic_sha, recorded.finalization_sha256,
            signed_hashes, True, _reference(reference["record_id"]), reference["fact_sha256"])
        receipts.append(rf.Rf1086YearGovernanceReceiptV2(receipt, observation))
        capital_ids.add(receipt_id)
    _require(capital_ids == set(chains)
        and {item.original.receipt_id for item in receipts} == set(evidence),
        "rf1086_source_governance_events_omitted")
    return rf.Rf1086VerifiedYearSourceContextV2(session.actor_id, True, command.company_id,
        command.income_year, company, identity_sha256, documents, tuple(receipts), True, projection)
