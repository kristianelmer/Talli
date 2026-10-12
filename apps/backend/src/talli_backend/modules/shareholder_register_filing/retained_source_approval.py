"""Full retained approval identity from saved evidence, without current rendering.

Private foundation for a later explicit retained archive reader. No existing
reader, claim, admission or serializer is widened here. Review SHA is a caller's
retained commitment: its captured review/permission correspondence belongs to
the archive validator, not this manifest composition layer.
"""
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

from . import public as rf
from .readiness_shape_v2 import matches_shape
from .retained_readiness import annual_binding, assert_preview
from .source_approval_encoding import _canonical, _require
from .source_production import _compose as manifest_v1_v2
from .source_production_v3 import _approved_shape, _basis_shape, _compose as manifest_v3
from .year_source import _sha, _uuid


def _legacy_basis_shape(basis):
    _require(type(basis) is rf.Rf1086SourceApprovalManifestBasis
             and type(basis.source) is rf.Rf1086YearSourceSnapshot
             and (basis.annual_readiness is None
                  or type(basis.annual_readiness) is rf.Rf1086AnnualReadinessProof)
             and type(basis.actor_id) is ActorId and basis.actor_id.kind is ActorKind.USER
             and type(basis.actor_id.subject) is UserId
             and type(basis.actor_id.subject.value) is str
             and type(basis.entitlement_id) is str and type(basis.review_sha256) is str
             and type(basis.acknowledged_warning_codes) is tuple
             and all(type(code) is str for code in basis.acknowledged_warning_codes)
             and (basis.predecessor is None or matches_shape(
                 basis.predecessor, rf.Rf1086SourceCorrectionPredecessor)))


def build_manifest(basis, *, preview_payload_sha256, preview_payload_text=None):
    """Rebuild every manifest field from retained evidence, not today's renderer.

Absent raw payload text means only the canonical saved preview is committed.
Both old and new source integrity remain their owner's contract; no recursive
annotation check narrows historically accepted economic numeric types.
"""
    try:
        if type(basis) is rf.Rf1086SourceApprovalManifestBasisV3:
            _basis_shape(basis)
            compose = manifest_v3
        else:
            _legacy_basis_shape(basis)
            compose = manifest_v1_v2
        source, preview = basis.source, basis.preview
        assert_preview(source, preview, preview_payload_sha256=preview_payload_sha256,
                       preview_payload_text=preview_payload_text)
        actor = _uuid(basis.actor_id.subject.value)
        entitlement = _uuid(basis.entitlement_id)
        _sha(basis.review_sha256)
        _require(preview.readiness_status == 'ready' and bool(preview.hovedskjema_xml)
                 and bool(preview.underskjema_xml)
                 and all(issue.level == 'warning' for issue in preview.readiness_issues))
        warnings = tuple(sorted({issue.code for issue in preview.readiness_issues}))
        binding = None
        if basis.annual_readiness is not None:
            binding = annual_binding(basis.annual_readiness, source, preview,
                preview_payload_sha256=preview_payload_sha256, preview_payload_text=preview_payload_text)
            warnings = basis.annual_readiness.required_warning_codes
        acknowledged = basis.acknowledged_warning_codes
        _require(all(bool(code) for code in acknowledged)
                 and len(set(acknowledged)) == len(acknowledged)
                 and set(acknowledged) == set(warnings))
        result = compose(basis, actor, entitlement, warnings, binding)
        _require(_approved_shape(result))
        return result
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError,
            RecursionError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def assert_matches(approved, basis, *, preview_payload_sha256, preview_payload_text=None):
    """Compare complete retained identity; this cannot authenticate a forged origin."""
    expected = build_manifest(basis, preview_payload_sha256=preview_payload_sha256,
                              preview_payload_text=preview_payload_text)
    try:
        if not (_approved_shape(approved)
                and approved.manifest_sha256 == expected.manifest_sha256
                and approved.document_order == expected.document_order
                and approved.underskjema_xml == expected.underskjema_xml
                and _canonical(approved.manifest) == _canonical(expected.manifest)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086ProductionError('payload_changed') from None
