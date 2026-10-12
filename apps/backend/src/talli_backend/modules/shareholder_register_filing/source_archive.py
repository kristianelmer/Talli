"""Full-year archive claim, managed head and original journal commitments."""
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from . import public as rf


def validate_source_submissions(query, snapshot, require):
    submissions={row.id:row for row in snapshot.production_submissions}
    approvals={row.id:row for row in snapshot.approvals}
    source_ids={row.id for row in snapshot.production_submissions if row.case_profile=='rf1086_full_year_v1'}
    claims=snapshot.source_submission_claims
    require(type(claims) is tuple and all(isinstance(c,rf.Rf1086SourceSubmissionClaim) for c in claims))
    require(len({c.submission_id.value for c in claims})==len(claims)
        and len({c.approval_id.value for c in claims})==len(claims)
        and {c.submission_id.value for c in claims}==source_ids)
    for claim in claims:
        row=submissions[claim.submission_id.value];approval=approvals[row.approval_id]
        prior=approval.manifest['predecessor']
        parent=None if prior is None else rf.SubmissionId(prior['submissionId'])
        rf.assert_rf1086_source_submission_claim(claim,approval_id=rf.ApprovalId(approval.id),
            manifest_sha256=approval.manifest_hash,expected_head=parent,actor_id=claim.claimed_by)
        require(claim.company_id==query.company_id and claim.income_year==query.income_year
            and claim.payload_sha256==row.payload_hash
            and str(claim.claimed_by.subject)==row.submitted_by==approval.approved_by
            and row.supersedes_submission_id==(None if parent is None else parent.value))
        _journal(row,approval,tuple(e for e in snapshot.production_events if e.submission_id==row.id),require)
    head=snapshot.submission_head
    if not source_ids:
        require(head is None)
        return
    require(isinstance(head,rf.Rf1086SubmissionHead) and head.company_id==query.company_id
        and isinstance(head.income_year,rf.IncomeYear) and type(head.income_year.value) is int
        and head.income_year==query.income_year and head.obligation=='aksjonaerregisteroppgaven'
        and head.environment=='production' and isinstance(head.submission_id,rf.SubmissionId)
        and head.submission_id.value in source_ids and type(head.updated_at) is str
        and datetime.fromisoformat(head.updated_at).tzinfo is not None)
    # A managed history has exactly one complete linear chain, with terminal
    # ancestors. Its leaf may still be sending, unknown or processing.
    children={};roots=[]
    for row in submissions.values():
        if row.supersedes_submission_id is None:roots.append(row.id)
        else:
            require(row.supersedes_submission_id in submissions and row.supersedes_submission_id not in children)
            parent=submissions[row.supersedes_submission_id]
            require(parent.status in ('accepted','rejected') and parent.feedback_state==parent.status)
            children[parent.id]=row.id
    require(len(roots)==1)
    visited=set();leaf=roots[0]
    while True:
        require(leaf not in visited);visited.add(leaf)
        if leaf not in children:break
        leaf=children[leaf]
    require(len(visited)==len(submissions) and leaf==head.submission_id.value)


def _journal(submission,approval,events,require):
    documents=approval.manifest['documentHashes']
    expected={('post_hovedskjema' if d['name']=='hovedskjema' else
        'post_underskjema:'+d['name'].removeprefix('underskjema_')):d['sha256'] for d in documents}
    mutations=set(expected)|{'confirm'}
    commitments={};successes={};keys={}
    for event in events:
        name=event.operation_name
        require(type(event.attempt) is int and 1<=event.attempt<=20
            and event.operation_state in ('prepared','succeeded','failed','unknown'))
        if name.startswith('reconciliation:'):
            require(event.body_hash is None and event.idempotency_key is None)
            continue
        require(name in mutations or name=='list_documents')
        if name in mutations:
            require(type(event.idempotency_key) is str and str(UUID(event.idempotency_key))==event.idempotency_key)
            require(event.idempotency_key not in keys or keys[event.idempotency_key]==name)
            keys[event.idempotency_key]=name
            commitment=(event.body_hash,event.idempotency_key)
            require(name not in commitments or commitments[name]==commitment)
            commitments[name]=commitment
            if name in expected:require(event.body_hash==expected[name])
        else:require(event.body_hash is None and event.idempotency_key is None)
        if event.operation_state=='succeeded':
            require(type(event.authority_reference) is str and bool(event.authority_reference)
                and (name not in successes or successes[name]==event.authority_reference))
            successes[name]=event.authority_reference
    main=successes.get('post_hovedskjema')
    if 'confirm' in commitments:
        require(main is not None and commitments['confirm'][0]==sha256(f'{main}:{len(documents)-1}'.encode()).hexdigest())
    if 'confirm' in successes:
        confirmation=json.loads(successes['confirm'])
        require(type(confirmation) is dict and set(confirmation)=={'dialogId','forsendelseId'}
            and all(type(value) is str and bool(value) for value in confirmation.values()))
    # Journal references are a projection of succeeded operations, not a source
    # from which to invent missing POST/confirmation evidence.
    require(dict(submission.authority_references)==successes)
    if submission.status in ('received','processing','accepted','rejected','action_required'):
        require(mutations<=successes.keys())
    for name in successes:
        if name.startswith('post_underskjema:'):require(main is not None)
    if 'confirm' in successes:require(set(expected)<=successes.keys())
