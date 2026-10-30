"""Retained v3 approval composition; current authority belongs to admission."""
from . import public as rf
from . import retained_source_approval


def _capture(basis, capture):
    if type(basis) is not rf.Rf1086SourceApprovalManifestBasisV3:
        raise rf.Rf1086ProductionError('basis_unavailable')
    rf.build_rf1086_retained_source_readiness_v2(basis.source, capture)
    if basis.preview != capture.preview:
        raise rf.Rf1086ProductionError('basis_unavailable')


def build_manifest(basis, capture):
    _capture(basis, capture)
    return retained_source_approval.build_manifest(basis,
        preview_payload_sha256=capture.payload_sha256, preview_payload_text=capture.payload_text)


def assert_matches(approved, basis, capture):
    _capture(basis, capture)
    retained_source_approval.assert_matches(approved, basis,
        preview_payload_sha256=capture.payload_sha256, preview_payload_text=capture.payload_text)
