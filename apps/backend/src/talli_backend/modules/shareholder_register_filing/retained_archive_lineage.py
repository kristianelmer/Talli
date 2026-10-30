"""Retained approval correspondence, without current rendering or admission.

A coherent captured chain is not proof of its authentic origin, an owner's
complete enumeration, original document bytes, or permission to file today.
"""
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

from . import public as rf
from .preparation import _retained_review_text, _validate_review_correspondence
from .retained_readiness import assert_preview, parse_annual_binding
from .retained_source_approval import build_manifest


def _review(lineage, approval, bridge, manifest_review, require):
    review = _retained_review_text(lineage, require)
    keys = {'version', 'binding', 'scope', 'comments', 'overrides', 'permission', 'pilot',
            'request', 'technicalReleaseReady'}
    schema = approval.manifest['schemaVersion']
    if schema == 'production-source-approval-v1':
        require(type(review) is dict and set(review) == keys | {'storedReleaseReady'})
        require(review['version'] == 'rf1086-source-review-v1' and review['storedReleaseReady'] is True)
    else:
        version, binding = {
            'production-source-approval-v2': ('rf1086-source-review-v2', 'rf1086-annual-readiness-binding-v1'),
            'production-source-approval-v3': ('rf1086-source-review-v3', 'rf1086-annual-readiness-binding-v2'),
        }[schema]
        require(type(review) is dict and set(review) == keys | {'annualReadiness', 'otherOverridesReady'})
        require(review['version'] == version and review['otherOverridesReady'] is True
                and review['annualReadiness'] == approval.manifest['annualReadiness']
                and review['annualReadiness']['schemaVersion'] == binding)
    _validate_review_correspondence(review, lineage, approval, bridge, manifest_review, require)


def validate(query, approval, projection, lineage, archive, require):
    source, preview, bridge = lineage.source, lineage.source_preview, lineage.bridge
    schema = approval.manifest['schemaVersion']
    require((type(source) is rf.Rf1086YearSourceSnapshot
             and schema in ('production-source-approval-v1', 'production-source-approval-v2'))
            or (type(source) is rf.Rf1086YearSourceSnapshotV2 and schema == 'production-source-approval-v3'))
    require(type(preview) is rf.Rf1086SourcePreview
            and type(bridge) is rf.Rf1086ArchiveSourceReviewBridge)
    # Legacy v1 archives may never have captured the raw preview. Do not invent
    # those bytes or claim complete history from the canonical commitment alone.
    raw_preview = None
    if archive.source_history is not None:
        captures = tuple(row for row in archive.source_history.source_previews
                         if row.preview.preview_id == preview.preview_id)
        require(len(captures) == 1)
        require(captures[0].preview == preview and captures[0].payload_sha256 == lineage.payload_sha256)
        raw_preview = captures[0].payload_text
    assert_preview(source, preview, preview_payload_sha256=lineage.payload_sha256,
                   preview_payload_text=raw_preview)
    expected = (preview.preview_id.value, str(query.company_id), int(query.income_year),
                source.source_id.value, source.source_sha256, lineage.payload_sha256)
    require((lineage.preview_id, lineage.company_id, lineage.income_year, lineage.source_id,
             lineage.source_sha256, lineage.payload_sha256) == expected)
    require((bridge.preview_id, bridge.company_id, bridge.income_year, bridge.source_id,
             bridge.source_sha256, bridge.payload_sha256) == expected)
    require(source.company_id == query.company_id and source.income_year == query.income_year)
    require(approval.id == lineage.approval_id and approval.preview_id == lineage.preview_id
            and approval.user_id == approval.approved_by == lineage.approved_by
            and approval.manifest_hash == lineage.manifest_sha256
            and approval.payload_hash == lineage.payload_sha256
            and approval.adapter_version == 'rf1086-source-production-v1')
    review = approval.manifest['review']
    require(review['sha256'] == lineage.review_sha256)
    annual = None
    if schema != 'production-source-approval-v1':
        annual = parse_annual_binding(approval.manifest['annualReadiness'], source, preview,
            preview_payload_sha256=lineage.payload_sha256, preview_payload_text=raw_preview)
    _review(lineage, approval, bridge, review, require)
    prior = approval.manifest['predecessor']
    predecessor = None if prior is None else rf.Rf1086SourceCorrectionPredecessor(
        rf.SubmissionId(prior['submissionId']), prior['manifestSha256'], prior['reason'])
    basis_type = (rf.Rf1086SourceApprovalManifestBasisV3 if schema == 'production-source-approval-v3'
                  else rf.Rf1086SourceApprovalManifestBasis)
    basis = basis_type(source=source, preview=preview,
        actor_id=ActorId(ActorKind.USER, UserId(approval.user_id)), entitlement_id=approval.entitlement_id,
        review_sha256=lineage.review_sha256, acknowledged_warning_codes=tuple(review['acknowledgedWarningCodes']),
        predecessor=predecessor, annual_readiness=annual)
    rebuilt = build_manifest(basis, preview_payload_sha256=lineage.payload_sha256,
                             preview_payload_text=raw_preview)
    serialize = (rf.serialize_rf1086_source_approval_manifest_v3 if schema == 'production-source-approval-v3'
                 else rf.serialize_rf1086_source_approval_manifest)
    require(rebuilt.manifest_sha256 == approval.manifest_hash
            and rebuilt.manifest == approval.manifest
            and serialize(rebuilt) == lineage.manifest_text)
    if schema == 'production-source-approval-v3':
        # JSON numeric equality alone would equate a bool/float with an integer.
        # V3's released serializer checks the supplied manifest's exact JSON
        # types and bytes; legacy numeric acceptance remains unchanged.
        supplied = rf.Rf1086SourceApprovalManifest(approval.manifest, approval.manifest_hash,
            rebuilt.document_order, rebuilt.underskjema_xml)
        require(serialize(supplied) == lineage.manifest_text)
    require(projection.source == 'rf1086-full-year-v1' and projection.setup_id is None
            and projection.status == preview.readiness_status
            and projection.issues == preview.readiness_issues
            and projection.preview == preview.preview_text
            and projection.hovedskjema_xml == preview.hovedskjema_xml
            and projection.underskjema_xml == rebuilt.underskjema_xml)
