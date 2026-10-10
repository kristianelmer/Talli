"""Versioned full-year approval identity; no persistence or provider authority.

Historical production-approval-v1 hashing remains in production.py unchanged.
This version orders stable shareholder IDs by UTF-8 bytes and hashes canonical
JSON with sorted keys. Neither locale nor the legacy UUID ordering applies.
"""
from talli_backend.shared.kernel import ActorKind

from . import public as rf
from .year_source import _sha, _uuid
from .source_approval_encoding import (
    _bytes, _canonical, _documents, _hash, _plain, _predecessor, _require,
)


def build_manifest(basis: rf.Rf1086SourceApprovalManifestBasis) -> rf.Rf1086SourceApprovalManifest:
    try:
        _require(isinstance(basis, rf.Rf1086SourceApprovalManifestBasis))
        source, preview = basis.source, basis.preview
        rf.assert_rf1086_year_source_integrity(source)
        rf.assert_rf1086_source_preview_matches(preview, source)
        _uuid(preview.preview_id.value)
        _require(basis.actor_id.kind is ActorKind.USER)
        actor_id = _uuid(str(basis.actor_id.subject))
        entitlement_id = _uuid(basis.entitlement_id)
        _sha(basis.review_sha256)
        _require(preview.readiness_status == "ready" and bool(preview.hovedskjema_xml)
                 and bool(preview.underskjema_xml)
                 and all(issue.level == "warning" for issue in preview.readiness_issues))
        warnings = tuple(sorted({issue.code for issue in preview.readiness_issues}))
        annual_binding = None
        if basis.annual_readiness is not None:
            annual = basis.annual_readiness
            annual_text = rf.serialize_rf1086_annual_readiness(annual, source, preview)
            _require(annual.readiness_status in ('ready', 'warning'))
            warnings = annual.required_warning_codes
            annual_binding = {
                'schemaVersion': 'rf1086-annual-readiness-binding-v1',
                'proofSha256': annual.proof_sha256,
                'proofTextSha256': _hash(annual_text),
                'proofText': annual_text,
            }
        acknowledged = basis.acknowledged_warning_codes
        _require(all(isinstance(code, str) and bool(code) for code in acknowledged)
                 and len(set(acknowledged)) == len(acknowledged)
                 and set(acknowledged) == set(warnings))

        return _compose(basis, actor_id, entitlement_id, warnings, annual_binding)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086ProductionError("basis_unavailable") from None


def _compose(basis, actor_id, entitlement_id, warnings, annual_binding):
    """Encode validated identity only; no rendering or live admission."""
    source, preview = basis.source, basis.preview
    order, xml, documents = _documents(preview)
    predecessor = _predecessor(basis.predecessor)
    freshness = source.freshness
    manifest = {
        "schemaVersion": "production-source-approval-v1",
        "companyId": str(source.company_id), "organizationNumber": source.command.case.company.org_number,
        "incomeYear": int(source.income_year), "userId": actor_id,
        "obligation": "aksjonaerregisteroppgaven", "caseProfile": "rf1086_full_year_v1",
        "adapterVersion": "rf1086-source-production-v1", "entitlementId": entitlement_id,
        "source": {"id": source.source_id.value, "version": source.version,
                   "sha256": source.source_sha256, "caseSha256": source.case_sha256},
        "preview": {"id": preview.preview_id.value, "renderingProfile": preview.rendering_profile,
                    "reviewTextSha256": _hash(preview.preview_text)},
        "freshness": {"companyIdentitySha256": freshness.company_identity_sha256,
                      "documentsSha256": freshness.documents_sha256,
                      "governanceReceiptsSha256": freshness.governance_receipts_sha256,
                      "governanceEnumerationSha256": freshness.governance_enumeration_sha256},
        "documentOrderVersion": "shareholder-id-utf8-sha256-v1", "documentHashes": documents,
        "review": {"sha256": basis.review_sha256, "acknowledgedWarningCodes": warnings},
        "predecessor": predecessor,
    }
    if annual_binding is not None:
        manifest['schemaVersion'] = 'production-source-approval-v2'
        manifest['annualReadiness'] = annual_binding
    return rf.Rf1086SourceApprovalManifest(manifest, _hash(_canonical(manifest)), order, xml)


def assert_matches(approved: rf.Rf1086SourceApprovalManifest,
                   basis: rf.Rf1086SourceApprovalManifestBasis) -> None:
    """Rebuild all keys and bytes; unknown fields/versions cannot be ignored."""
    try:
        expected = build_manifest(basis)
        if not (isinstance(approved, rf.Rf1086SourceApprovalManifest)
                and type(approved.manifest_sha256) is str
                and approved.manifest_sha256 == expected.manifest_sha256
                and approved.document_order == expected.document_order
                and approved.underskjema_xml == expected.underskjema_xml
                and _canonical(approved.manifest) == _canonical(expected.manifest)):
            raise rf.Rf1086ProductionError("payload_changed")
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086ProductionError("payload_changed") from None


def serialize_manifest(approved: rf.Rf1086SourceApprovalManifest) -> str:
    """Encode the approved version without applying the legacy hash algorithm."""
    try:
        _require(isinstance(approved, rf.Rf1086SourceApprovalManifest))
        text = _canonical(approved.manifest)
        _require(approved.manifest.get('schemaVersion') in ('production-source-approval-v1', 'production-source-approval-v2')
                 and _hash(text) == approved.manifest_sha256)
        return text
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
