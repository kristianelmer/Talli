"""Versioned full-year approval identity; no persistence or provider authority.

Historical production-approval-v1 hashing remains in production.py unchanged.
This version orders stable shareholder IDs by UTF-8 bytes and hashes canonical
JSON with sorted keys. Neither locale nor the legacy UUID ordering applies.
"""
from collections.abc import Mapping
import hashlib
import json

from talli_backend.shared.kernel import ActorKind

from . import public as rf
from .year_source import _sha, _uuid


def _require(condition: bool) -> None:
    if not condition:
        raise rf.Rf1086ProductionError("basis_unavailable")


def _bytes(value: str) -> bytes:
    # Reject invalid Unicode instead of replacing bytes in an approval identity.
    return value.encode("utf-8", errors="strict")


def _hash(value: str) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _canonical(value) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


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
        acknowledged = basis.acknowledged_warning_codes
        _require(all(isinstance(code, str) and bool(code) for code in acknowledged)
                 and len(set(acknowledged)) == len(acknowledged)
                 and set(acknowledged) == set(warnings))

        # Names remain byte-exact stable IDs. Never trim, normalize, parse as
        # UUIDs, or use insertion order, which could reassign journal operations.
        names = tuple(preview.underskjema_xml)
        _require(all(isinstance(name, str) and bool(name.strip()) and "\x00" not in name for name in names))
        names = tuple(sorted(names, key=_bytes))
        # The existing journal limits operation names to 120 characters. Stable
        # derived keys fit that contract without narrowing shareholder IDs.
        keys = {name: "source_" + _hash("rf1086-source-shareholder-v1:" + name) for name in names}
        _require(len(set(keys.values())) == len(names))
        order = tuple(keys[name] for name in names)
        xml = {keys[name]: preview.underskjema_xml[name] for name in names}
        documents = [{"name": "hovedskjema", "sha256": _hash(preview.hovedskjema_xml)}]
        documents.extend({"name": "underskjema_" + keys[name], "shareholderId": name,
                          "sha256": _hash(preview.underskjema_xml[name])} for name in names)
        predecessor = None
        if basis.predecessor is not None:
            prior = basis.predecessor
            _require(isinstance(prior, rf.Rf1086SourceCorrectionPredecessor)
                     and isinstance(prior.submission_id, rf.SubmissionId)
                     and isinstance(prior.reason, str) and bool(prior.reason.strip()))
            predecessor = {"submissionId": _uuid(prior.submission_id.value),
                           "manifestSha256": _sha(prior.manifest_sha256), "reason": prior.reason}
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
        return rf.Rf1086SourceApprovalManifest(manifest, _hash(_canonical(manifest)), order, xml)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086ProductionError("basis_unavailable") from None


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
