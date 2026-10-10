"""Pure approval v3, binding v2 evidence without enabling a runtime consumer."""
from collections.abc import Mapping

from talli_backend.shared.kernel import ActorId, ActorKind, UserId

from . import public as rf
from .annual_readiness_storage_v2 import inspect_binding
from .readiness_shape_v2 import matches_shape
from .source_approval_encoding import _canonical, _documents, _hash, _predecessor, _require
from .year_source import _sha, _uuid


def _basis_shape(basis):
    _require(type(basis) is rf.Rf1086SourceApprovalManifestBasisV3
             and type(basis.source) is rf.Rf1086YearSourceSnapshotV2
             and matches_shape(basis.preview, rf.Rf1086SourcePreview)
             and type(basis.annual_readiness) is rf.Rf1086AnnualReadinessProofV2
             and type(basis.actor_id) is ActorId
             and basis.actor_id.kind is ActorKind.USER
             and type(basis.actor_id.subject) is UserId
             and type(basis.actor_id.subject.value) is str
             and type(basis.entitlement_id) is str
             and type(basis.review_sha256) is str
             and type(basis.acknowledged_warning_codes) is tuple
             and all(type(code) is str for code in basis.acknowledged_warning_codes)
             and (basis.predecessor is None or matches_shape(
                 basis.predecessor, rf.Rf1086SourceCorrectionPredecessor)))


def build_manifest(basis: rf.Rf1086SourceApprovalManifestBasisV3) -> rf.Rf1086SourceApprovalManifest:
    try:
        _basis_shape(basis)
        source, preview, annual = basis.source, basis.preview, basis.annual_readiness
        # The source owner accepts the historical numeric representations in
        # economic fields. Do not replace that contract with annotation coercion.
        rf.assert_rf1086_year_source_integrity_v2(source)
        rf.assert_rf1086_source_preview_matches(preview, source)
        _uuid(preview.preview_id.value)
        actor_id = _uuid(basis.actor_id.subject.value)
        entitlement_id = _uuid(basis.entitlement_id)
        _sha(basis.review_sha256)
        _require(preview.readiness_status == 'ready' and bool(preview.hovedskjema_xml)
                 and bool(preview.underskjema_xml)
                 and all(issue.level == 'warning' for issue in preview.readiness_issues))
        annual_text = rf.serialize_rf1086_annual_readiness_v2(annual, source, preview)
        _require(annual.readiness_status in ('ready', 'warning'))
        warnings = annual.required_warning_codes
        acknowledged = basis.acknowledged_warning_codes
        _require(all(bool(code) for code in acknowledged)
                 and len(set(acknowledged)) == len(acknowledged)
                 and set(acknowledged) == set(warnings))
        annual_binding = {'schemaVersion': 'rf1086-annual-readiness-binding-v2',
                          'proofSha256': annual.proof_sha256,
                          'proofTextSha256': _hash(annual_text), 'proofText': annual_text}
        return _compose(basis, actor_id, entitlement_id, warnings, annual_binding)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def _compose(basis, actor_id, entitlement_id, warnings, annual_binding):
    """Encode validated identity only; no rendering or live admission."""
    source, preview = basis.source, basis.preview
    order, xml, documents = _documents(preview)
    predecessor = _predecessor(basis.predecessor)
    freshness = source.freshness
    manifest = {
        'schemaVersion': 'production-source-approval-v3',
        'companyId': str(source.company_id), 'organizationNumber': source.command.case.company.org_number,
        'incomeYear': int(source.income_year), 'userId': actor_id,
        'obligation': 'aksjonaerregisteroppgaven', 'caseProfile': 'rf1086_full_year_v1',
        'adapterVersion': 'rf1086-source-production-v1', 'entitlementId': entitlement_id,
        'source': {'codec': 'rf1086-year-source-v2', 'id': source.source_id.value,
                   'version': source.version, 'sha256': source.source_sha256,
                   'caseSha256': source.case_sha256},
        'preview': {'id': preview.preview_id.value, 'renderingProfile': preview.rendering_profile,
                    'reviewTextSha256': _hash(preview.preview_text)},
        'freshness': {'companyIdentitySha256': freshness.company_identity_sha256,
                      'documentsSha256': freshness.documents_sha256,
                      'governanceReceiptsSha256': freshness.governance_receipts_sha256,
                      'governanceOriginalEnumerationSha256': freshness.governance_original_enumeration_sha256,
                      'governanceChainEnumerationSha256': freshness.governance_chain_enumeration_sha256,
                      'governanceProjectionSha256': freshness.governance_projection_sha256},
        'documentOrderVersion': 'shareholder-id-utf8-sha256-v1', 'documentHashes': documents,
        'review': {'sha256': basis.review_sha256, 'acknowledgedWarningCodes': warnings},
        'predecessor': predecessor,
        'annualReadiness': annual_binding,
    }
    approved = rf.Rf1086SourceApprovalManifest(manifest, _hash(_canonical(manifest)), order, xml)
    _require(_approved_shape(approved))
    return approved


def _plain_shape(value):
    # V3 manifests contain only exact JSON strings/integers/null and containers.
    # No numeric coercion, dataclass flattening or scalar subclass substitution.
    if type(value) in (str, int, type(None)):
        return True
    if type(value) is tuple:
        return all(_plain_shape(item) for item in value)
    return (isinstance(value, Mapping)
            and all(type(key) is str and _plain_shape(item) for key, item in value.items()))


def _approved_shape(approved):
    return (type(approved) is rf.Rf1086SourceApprovalManifest
            and isinstance(approved.manifest, Mapping) and _plain_shape(approved.manifest)
            and type(approved.manifest_sha256) is str
            and type(approved.document_order) is tuple
            and all(type(item) is str for item in approved.document_order)
            and isinstance(approved.underskjema_xml, Mapping)
            and all(type(key) is str and type(value) is str
                    for key, value in approved.underskjema_xml.items()))


def assert_matches(approved: rf.Rf1086SourceApprovalManifest,
                   basis: rf.Rf1086SourceApprovalManifestBasisV3) -> None:
    """Rebuild every field and renderer byte; a digest alone is not authority."""
    try:
        expected = build_manifest(basis)
        if not (_approved_shape(approved)
                and approved.manifest_sha256 == expected.manifest_sha256
                and approved.document_order == expected.document_order
                and approved.underskjema_xml == expected.underskjema_xml
                and _canonical(approved.manifest) == _canonical(expected.manifest)):
            raise rf.Rf1086ProductionError('payload_changed')
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086ProductionError('payload_changed') from None


def serialize_manifest(approved: rf.Rf1086SourceApprovalManifest) -> str:
    """V3 byte/hash integrity only; use assert_matches for source-bound identity."""
    try:
        _require(_approved_shape(approved))
        manifest = approved.manifest
        _require(manifest.get('schemaVersion') == 'production-source-approval-v3'
                 and manifest['source']['codec'] == 'rf1086-year-source-v2')
        inspect_binding(manifest['annualReadiness'])
        text = _canonical(manifest)
        _require(_hash(text) == approved.manifest_sha256)
        return text
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
