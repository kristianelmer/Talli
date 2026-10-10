"""Documents-first retained stream fixtures; no SQL, Auth or blob-store proof.

DocumentRecord metadata and exact content/receipt identities exist before RF
constructors consume them. Governance/annual owner labels and saved journals are
synthetic commitments; every exported Documents original is independently real.
"""
from dataclasses import asdict, replace
from datetime import timedelta
from hashlib import sha256
import json
from uuid import UUID, uuid5, NAMESPACE_URL

from talli_backend.modules.documents import public as documents
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IncomeYear
from test_rf1086_annual_readiness_v2 import inputs_for
from test_rf1086_archive_history_v6 import capture_source, capture_observation, capture_withdrawal, withdraw
from test_rf1086_register_observation import basis as register_basis
from test_rf1086_source_approval_archive import source_archive
from test_rf1086_source_preview import preview_source
from test_rf1086_source_production import source_case, source_for
from test_rf1086_source_submission_archive import source_submission_archive
from test_rf1086_year_source import ACTOR, COMPANY, DOCUMENT, NOW
from test_rf1086_year_source_v2 import CONFIRMED, identity, projection, register_fact, digest


def original(number, *, document_id=None, version=0, document_type='share_register',
             source_year=2024, content=None, linked_to='workspace', created_at=None,
             content_type='application/pdf'):
    """Make exact portable bytes first; metadata-only revisions retain one ID."""
    content = (b'%PDF-1.7\nRetained original \x00\xff ' + str(number).encode()) if content is None else content
    created = NOW - timedelta(days=20) if created_at is None else created_at
    doc = documents.DocumentRecord(documents.DocumentId(document_id or identity(number)),
        COMPANY, IncomeYear(source_year), document_type, f'Original-{number}-v{version}.pdf',
        linked_to, documents.DocumentStatus.STORED, 10,
        f'{COMPANY}/{source_year}/{document_id or identity(number)}/original', content_type,
        len(content), sha256(content).hexdigest(), ACTOR, created, None, None)
    receipt = documents.RetainedDocumentOriginalReceipt(identity(70000 + number * 10 + version),
        doc.document_id, doc.company_id, doc.income_year, documents.document_metadata_sha256(doc),
        doc.content_sha256, doc.byte_length, created + timedelta(seconds=1))
    result = documents.RetainedDocumentOriginalSnapshot(doc, documents.RetainedDocumentOriginal(receipt, content))
    # Public owner codec validates actual byte length/hash and metadata, before RF consumes it.
    text = documents.serialize_retained_document_original(result, query=original_query(result))
    assert documents.parse_retained_document_original(text, query=original_query(result)) == result
    return result


def original_query(value):
    row = value.original.receipt
    return documents.RetainedDocumentOriginalQuery(row.document_id, row.company_id,
        row.source_income_year, row.metadata_sha256, row.content_sha256, row.byte_length)


def year_evidence(value):
    doc, receipt = value.document, value.original.receipt
    return rf.Rf1086YearDocumentEvidence(str(doc.document_id), doc.company_id,
        doc.content_sha256, doc.content_sha256, doc.document_type, doc.status.value,
        doc.byte_length, doc.created_at, receipt.metadata_sha256, doc.income_year)


def register_evidence(value, role):
    doc, receipt = value.document, value.original.receipt
    return rf.Rf1086RegisterDocumentEvidence(str(doc.document_id), doc.company_id,
        doc.content_sha256, doc.content_sha256, doc.byte_length, doc.document_type,
        doc.status.value, doc.created_at, receipt.metadata_sha256, role, doc.income_year)


def _observation(command, index, number, confirmed_at, originals):
    before, after = rf.rf1086_event_register_states(command.case, index)
    event = command.case.events[index]
    template, _ = register_basis(event.type)
    docs = tuple(register_evidence(value, role) for value, role in zip(originals,
        ('register_before', 'register_after', 'registration'), strict=True))
    record = replace(template, company_id=command.company_id, actor_id=command.actor_id,
        income_year=command.income_year, effective_at=event.timestamp, event_kind=event.type,
        before=before, after=after, documents=docs)
    context = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True,
        command.company_id, command.income_year, docs, True)
    return rf.prepare_rf1086_register_observation(record, context=context,
        observation_id=rf.Rf1086RegisterObservationId(identity(number)), confirmed_at=confirmed_at)


def _approved(archive):
    source = archive.source_history.year_sources[-1]
    preview = preview_source(source)[0]
    payload = rf.serialize_rf1086_source_preview(preview)
    capture = rf.Rf1086ArchiveSourcePreview(preview, payload, sha256(payload.encode()).hexdigest(),
        ACTOR.subject.value, (CONFIRMED + timedelta(seconds=1)).isoformat())
    template = source_archive()
    line, approval = template.source_approval_lineage[0], template.approvals[0]
    bridge = replace(line.bridge, preview_id=preview.preview_id.value,
        source_id=source.source_id.value, source_sha256=source.source_sha256,
        payload_sha256=capture.payload_sha256, created_at=capture.created_at)
    annual = rf.build_rf1086_annual_readiness_v2(source, preview, inputs_for(source))
    proof_text = rf.serialize_rf1086_annual_readiness_v2(annual, source, preview)
    binding = dict(schemaVersion='rf1086-annual-readiness-binding-v2', proofSha256=annual.proof_sha256,
        proofTextSha256=sha256(proof_text.encode()).hexdigest(), proofText=proof_text)
    review = json.loads(line.review_text)
    review.pop('storedReleaseReady')
    review.update(version='rf1086-source-review-v3', binding=asdict(bridge),
        otherOverridesReady=True, annualReadiness=binding)
    review['scope'].update(previewId=bridge.preview_id, sourceId=bridge.source_id,
        sourceSha256=bridge.source_sha256, warningCodes=list(annual.required_warning_codes))
    review_text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    approved = rf.build_rf1086_source_approval_manifest_v3(rf.Rf1086SourceApprovalManifestBasisV3(
        source, preview, annual, ACTOR, approval.entitlement_id, sha256(review_text.encode()).hexdigest(),
        annual.required_warning_codes))
    approval = replace(approval, preview_id=bridge.preview_id, payload_hash=bridge.payload_sha256,
        manifest_hash=approved.manifest_sha256, manifest=approved.manifest, approved_at=capture.created_at)
    line = replace(line, preview_id=bridge.preview_id, source_id=bridge.source_id,
        source_sha256=bridge.source_sha256, payload_sha256=bridge.payload_sha256,
        manifest_sha256=approved.manifest_sha256, manifest_text=rf.serialize_rf1086_source_approval_manifest_v3(approved),
        review_text=review_text, review_sha256=sha256(review_text.encode()).hexdigest(), created_at=capture.created_at,
        source=source, source_preview=preview, bridge=bridge)
    saved = replace(template.previews[0], id=bridge.preview_id, status=preview.readiness_status,
        issues=preview.readiness_issues, preview=preview.preview_text, hovedskjema_xml=preview.hovedskjema_xml,
        underskjema_xml=approved.underskjema_xml, created_at=capture.created_at)
    return replace(archive, previews=(saved,), approvals=(approval,), source_approval_lineage=(line,),
        source_history=replace(archive.source_history, source_previews=(capture,), review_bridges=(bridge,)))


def _submitted(archive, status, *, bound_feedback):
    template = source_submission_archive(status='accepted' if status != 'rejected' else 'rejected')
    approval = archive.approvals[0]
    claim = replace(template.source_submission_claims[0], approval_id=rf.ApprovalId(approval.id),
        manifest_sha256=approval.manifest_hash, payload_sha256=approval.payload_hash, claimed_at=approval.approved_at)
    submission = replace(template.production_submissions[0], approval_id=approval.id,
        entitlement_id=approval.entitlement_id, payload_hash=approval.payload_hash,
        status=status, authority_references={}, feedback_state='sent', feedback_artifact_count=0)
    events, refs, feedback, originals = [], {}, (), []
    if status != 'approved':
        event = template.production_events[0]
        for document in approval.manifest['documentHashes']:
            name = ('post_hovedskjema' if document['name'] == 'hovedskjema' else
                'post_underskjema:' + document['name'].removeprefix('underskjema_'))
            reference = 'retained-main' if name == 'post_hovedskjema' else 'retained-post'
            events.append(replace(event, id=str(uuid5(NAMESPACE_URL, name)), operation_name=name,
                body_hash=document['sha256'], idempotency_key=str(uuid5(NAMESPACE_URL, 'key:' + name)),
                authority_reference=reference))
            refs[name] = reference
        refs['confirm'] = json.dumps({'dialogId': identity(700), 'forsendelseId': identity(701)}, separators=(',', ':'))
        events.append(replace(event, id=identity(702), operation_name='confirm',
            body_hash=sha256(f'retained-main:{len(approval.manifest["documentHashes"])-1}'.encode()).hexdigest(),
            idempotency_key=identity(703), authority_reference=refs['confirm'], resulting_status='received'))
        feedback = template.feedback_artifacts
        if bound_feedback:
            from datetime import datetime
            rows = []
            for index, artifact in enumerate(feedback):
                value = original(9000 + index, document_id=artifact.document_id,
                    document_type='authority_feedback', source_year=int(archive.income_year),
                    content=b'<receipt>Exact retained feedback \x00 ' + status.encode() + b' ' + str(index).encode() + b'</receipt>',
                    linked_to='production_filing_submission:' + submission.id,
                    created_at=datetime.fromisoformat(artifact.retrieved_at), content_type=artifact.content_type)
                receipt = value.original.receipt
                originals.append(value)
                rows.append(replace(artifact, sha256=receipt.content_sha256, byte_length=receipt.byte_length,
                    original_id=receipt.original_id, original_metadata_sha256=receipt.metadata_sha256,
                    original_source_income_year=int(receipt.source_income_year), original_retained_at=receipt.retained_at.isoformat()))
            feedback = tuple(rows)
        events.extend(replace(e, artifact_hashes=tuple(row.sha256 for row in feedback))
                      for e in template.production_events[-1:])
        submission = replace(submission, authority_references=refs, feedback_state=status,
            feedback_artifact_count=len(feedback))
    return replace(archive, production_submissions=(submission,), source_submission_claims=(claim,),
        submission_head=replace(template.submission_head, updated_at=claim.claimed_at),
        production_events=tuple(events), feedback_artifacts=feedback), originals


def retained_stream_fixture(kind='cash_issue', amendments=0, status='approved', *, legacy=False,
                            independent=False, bound_feedback=True):
    # All metadata/content/receipts precede construction of the RF evidence they back.
    old_base = original(100, document_id=DOCUMENT, version=0, document_type='shareholder_source')
    new_base = original(100, document_id=DOCUMENT, version=1, document_type='shareholder_source')
    version_documents = [tuple(original(5000 + role, version=version) for role in range(3))
                         for version in range(amendments + 1)]
    extra_documents = tuple(original(6000 + role) for role in range(3)) if independent else ()
    originals = [new_base, *(value for rows in version_documents for value in rows), *extra_documents]
    old = source_for(source_case(kind), document=year_evidence(new_base))
    command = old.command
    index = next(e.event_index for e in command.event_evidence if e.governance_receipt_id is not None)
    observations = [_observation(command, index, 1000 + n,
        NOW - timedelta(days=3) if n == 0 else NOW + timedelta(hours=n), rows)
        for n, rows in enumerate(version_documents)]
    first, effective = observations[0], observations[-1]
    withdrawals, links, previous = [], [], None
    for n in range(1, amendments + 1):
        receipt = withdraw(observations[n - 1], 3000 + n, observations[n].confirmed_at - timedelta(seconds=1))
        withdrawals.append(receipt)
        head = rf.Rf1086YearGovernanceHeadV2(identity(2000 + n), n, digest(['amendment', n]))
        links.append(rf.Rf1086YearGovernanceLinkV2(head, previous, receipt.withdrawal_id.value,
            receipt.withdrawal_sha256, register_fact(observations[n - 1]), register_fact(observations[n]),
            observations[n].confirmed_at))
        previous = head
    original_receipt = replace(old.governance_receipts[0], register_observation_id=first.observation_id.value,
        register_observation_sha256=first.fact_sha256)
    original_time = NOW - timedelta(days=2)
    chain = rf.Rf1086YearGovernanceChainV2(original_receipt.receipt_id, command.company_id,
        command.income_year, kind, original_receipt.finalization_sha256, digest(['anchor', kind]),
        original_time, register_fact(first), tuple(links), amendments,
        digest(['owner-chain', kind, amendments]), previous, register_fact(effective),
        links[-1].recorded_at if links else original_time)
    documents = (year_evidence(new_base), *(year_evidence(value) for value in version_documents[-1]))
    command = replace(command, documents=documents)
    previous_source = source_for(source_case('no_activity'), document=year_evidence(old_base)) if legacy else None
    if previous_source is not None:
        originals.append(old_base)
        command = replace(command, supersedes_source_id=previous_source.source_id,
            supersedes_source_sha256=previous_source.source_sha256, correction_reason='Retained source correction')
    context = rf.Rf1086VerifiedYearSourceContextV2(command.actor_id, True, command.company_id,
        command.income_year, command.case.company, old.freshness.company_identity_sha256,
        documents, (rf.Rf1086YearGovernanceReceiptV2(original_receipt, effective),), True,
        projection((chain,), original_sha=old.freshness.governance_enumeration_sha256))
    source = rf.prepare_rf1086_year_source_v2(command, context=context,
        source_id=rf.Rf1086YearSourceId(identity(6600)), confirmed_at=CONFIRMED, previous=previous_source)
    sources = (previous_source, source) if legacy else (source,)
    if independent:
        observations.append(_observation(command, index, 1900, NOW + timedelta(hours=5), extra_documents))
    history = rf.Rf1086ArchiveSourceHistory(sources,
        rf.Rf1086ArchiveYearSourceHead(source.company_id, source.income_year, source.source_id,
            source.version, source.source_sha256), tuple(observations), (), (),
        tuple(map(capture_source, sources)), tuple(map(capture_observation, observations)))
    archive = rf.Rf1086ArchiveSnapshot(source.company_id, source.income_year, source_history=history,
        overrides=(), withdrawal_capture_records=tuple(map(capture_withdrawal, withdrawals)))
    if status != 'unapproved':
        archive = _approved(archive)
        archive, feedback = _submitted(archive, status, bound_feedback=bound_feedback)
        originals.extend(feedback)
    query = rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, ACTOR)
    rf.serialize_rf1086_archive_v6(archive, query=query)
    return archive, {original_query(value): value for value in originals}


class DocumentsFactory:
    def __init__(self, originals, *, actor_id=ACTOR, failure=None):
        self.originals, self.actor_id, self.failure = originals, actor_id, failure
        self.sessions, self.reads = [], []

    async def session(self, token):
        self.sessions.append(token)
        return self

    async def read_retained_evidence(self, query):
        self.reads.append(query)
        if self.failure is not None:
            raise self.failure
        if query not in self.originals:
            raise documents.DocumentsError.not_found()
        return self.originals[query]
