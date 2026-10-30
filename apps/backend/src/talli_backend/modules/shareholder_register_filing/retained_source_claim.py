"""Approval-v3 header identity only, without source or admission authority."""
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

from . import public as rf
from .annual_readiness_storage_v2 import inspect_binding
from .source_claim import (_approval_header, _approval_identity,
                           _approval_predecessor, _require)


def inspect_approval(value, *, approval_id, manifest_sha256, actor_id):
    """Bind actor/header/hash and the annual envelope, not its source or policy.

    Full retained archive validation separately proves the saved source, XML,
    annual assessment and review correspondence. Neither check grants live
    access, fresh admission, authentic provenance or permission to send.
    """
    try:
        _require(type(value) is rf.Rf1086RetainedSourceApproval
            and type(value.approval) is rf.Rf1086ApprovalRecord
            and type(approval_id) is rf.ApprovalId
            and type(actor_id) is ActorId and actor_id.kind is ActorKind.USER
            and type(actor_id.subject) is UserId)
        approval, manifest = _approval_header(value, approval_id=approval_id,
            manifest_sha256=manifest_sha256, actor_id=actor_id)
        version = manifest.get('schemaVersion')
        _require(version == 'production-source-approval-v3'
            and type(manifest.get('source')) is dict
            and manifest['source'].get('codec') == 'rf1086-year-source-v2')
        inspect_binding(manifest['annualReadiness'])
        _approval_identity(approval, manifest, version)
        return _approval_predecessor(manifest)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError,
            RecursionError, rf.Rf1086YearSourceError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
