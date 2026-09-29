"""Retained claim identities; freshness and provider dispatch belong to admission."""
from datetime import datetime
import hashlib
import json

from talli_backend.shared.kernel import ActorKind
from . import public as rf
from .source_production import _canonical
from .year_source import _sha, _uuid


def _require(value):
    if not value:
        raise rf.Rf1086ProductionError('basis_unavailable')


def _time(value):
    _require(type(value) is str and datetime.fromisoformat(value).tzinfo is not None)


def inspect_approval(value, *, approval_id, manifest_sha256, actor_id):
    """Validate identity before preflight; admission rebuilds all source/XML fields."""
    try:
        _require(isinstance(value,rf.Rf1086RetainedSourceApproval))
        a=value.approval
        _require(isinstance(a,rf.Rf1086ApprovalRecord) and isinstance(approval_id,rf.ApprovalId)
            and actor_id.kind is ActorKind.USER and a.id==approval_id.value
            and a.user_id==a.approved_by==str(actor_id.subject)
            and a.case_profile=='rf1086_full_year_v1' and a.adapter_version=='rf1086-source-production-v1'
            and a.obligation=='aksjonaerregisteroppgaven' and type(a.income_year) is int
            and 2000<=a.income_year<=2100 and a.manifest_hash==manifest_sha256)
        for identity in (a.id,a.company_id,a.user_id,a.preview_id,a.entitlement_id):_uuid(identity)
        for digest in (a.payload_hash,a.manifest_hash,manifest_sha256):_sha(digest)
        _time(a.approved_at)
        if a.invalidated_at is not None:_time(a.invalidated_at)
        _require(type(value.manifest_text) is str)
        manifest=json.loads(value.manifest_text)
        _require(type(manifest) is dict and _canonical(manifest)==value.manifest_text
            and _canonical(a.manifest)==value.manifest_text
            and hashlib.sha256(value.manifest_text.encode('utf-8')).hexdigest()==manifest_sha256)
        version = manifest.get('schemaVersion')
        _require(version in ('production-source-approval-v1', 'production-source-approval-v2'))
        if version == 'production-source-approval-v2':
            from .annual_readiness_storage import inspect_binding
            inspect_binding(manifest['annualReadiness'])
        else:
            _require('annualReadiness' not in manifest)
        expected={'schemaVersion':version,'companyId':a.company_id,
            'incomeYear':a.income_year,'userId':a.user_id,'entitlementId':a.entitlement_id,
            'caseProfile':a.case_profile,'adapterVersion':a.adapter_version,'obligation':a.obligation}
        _require(all(manifest[key]==item and type(manifest[key]) is type(item) for key,item in expected.items())
            and manifest['preview']['id']==a.preview_id)
        _sha(manifest['review']['sha256'])
        prior=manifest['predecessor']
        if prior is None:return None
        _require(type(prior) is dict and set(prior)=={'submissionId','manifestSha256','reason'}
            and type(prior['reason']) is str and bool(prior['reason'].strip()))
        return rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(_uuid(prior['submissionId'])),
            _sha(prior['manifestSha256']),prior['reason'])
    except rf.Rf1086ProductionError:raise
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def assert_claim(value, *, approval_id, manifest_sha256, expected_head, actor_id):
    try:
        _require(isinstance(value,rf.Rf1086SourceSubmissionClaim)
            and isinstance(value.submission_id,rf.SubmissionId)
            and isinstance(value.approval_id,rf.ApprovalId)
            and value.approval_id==approval_id and value.manifest_sha256==manifest_sha256
            and value.predecessor_submission_id==expected_head
            and value.claimed_by==actor_id and actor_id.kind is ActorKind.USER
            and isinstance(value.company_id,rf.CompanyId) and isinstance(value.income_year,rf.IncomeYear))
        for identity in (value.submission_id.value,value.approval_id.value,str(value.company_id),str(actor_id.subject)):_uuid(identity)
        for digest in (value.manifest_sha256,value.payload_sha256):_sha(digest)
        _require(type(value.income_year.value) is int and 2000<=int(value.income_year)<=2100)
        if expected_head is not None:
            _require(isinstance(expected_head,rf.SubmissionId) and expected_head!=value.submission_id)
            _uuid(expected_head.value)
        _time(value.claimed_at)
    except rf.Rf1086ProductionError:raise
    except (ValueError,TypeError,AttributeError,UnicodeError,rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
