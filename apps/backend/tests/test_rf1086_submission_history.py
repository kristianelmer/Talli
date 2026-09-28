"""No timestamp or actor filter may select among competing production filings."""
from dataclasses import replace
from itertools import permutations
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_correction import CorrectionHarness, predecessor_snapshot
from test_rf1086_source_approval import ApprovalHarness
from test_rf1086_year_source import COMPANY, YEAR


def chain(count=3):
    root = predecessor_snapshot().submission
    return tuple(replace(root, id=str(UUID(int=1000+i)),
        supersedes_submission_id=str(UUID(int=999+i)) if i else None,
        case_profile='rf1086_full_year_v1' if i else root.case_profile,
        adapter_version='rf1086-source-production-v1' if i else root.adapter_version)
        for i in range(count))


def prior(row):
    return rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(row.id), 'a'*64, 'Corrected facts')


def check(rows, predecessor):
    rf.assert_rf1086_submission_predecessor(rows, company_id=COMPANY,
        income_year=YEAR, predecessor=predecessor)


def test_initial_filing_requires_empty_history():
    check((), None)
    with pytest.raises(rf.Rf1086ProductionError): check(chain(1), None)
    with pytest.raises(rf.Rf1086ProductionError): check((), prior(chain(1)[0]))


def test_mixed_profile_chain_is_selected_by_links_independent_of_order_or_timestamps():
    rows=chain()
    rows=(replace(rows[0],created_at='2099-01-01'), rows[1], replace(rows[2],created_at='2000-01-01'))
    for ordering in permutations(rows):
        check(ordering, prior(rows[-1]))
        with pytest.raises(rf.Rf1086ProductionError): check(ordering, prior(rows[0]))


@pytest.mark.parametrize('status', ['approved', 'sending', 'received', 'processing', 'unknown', 'action_required', 'failed'])
def test_uncertain_or_nonterminal_head_requires_reconciliation(status):
    row=replace(chain(1)[0],status=status,feedback_state=status)
    with pytest.raises(rf.Rf1086ProductionError): check((row,), prior(row))


@pytest.mark.parametrize('defect', ['fork','roots','missing_parent','self_parent','cycle','detached_cycle',
    'duplicate','wrong_company','wrong_year','bool_year','wrong_obligation','wrong_environment',
    'unknown_profile','wrong_adapter','malformed_id','unknown_parent','feedback_mismatch','uncertain_ancestor'])
def test_incomplete_or_ambiguous_history_cannot_authorize_correction(defect):
    rows=chain(); a,b,c=rows
    if defect=='fork': rows=(a,b,replace(c,supersedes_submission_id=a.id))
    if defect=='roots': rows=(a,b,replace(c,supersedes_submission_id=None))
    if defect=='missing_parent': rows=(b,c)
    if defect=='self_parent': rows=(a,b,replace(c,supersedes_submission_id=c.id))
    if defect=='cycle': rows=(replace(a,supersedes_submission_id=c.id),b,c)
    if defect=='detached_cycle': rows=(a,replace(b,supersedes_submission_id=c.id),c)
    if defect=='duplicate': rows=(a,b,c,c)
    if defect=='wrong_company': rows=(a,b,replace(c,company_id=str(UUID(int=9))))
    if defect=='wrong_year': rows=(a,b,replace(c,income_year=int(YEAR)-1))
    if defect=='bool_year': rows=(a,b,replace(c,income_year=True))
    if defect=='wrong_obligation': rows=(a,b,replace(c,obligation='skattemelding'))
    if defect=='wrong_environment': rows=(a,b,replace(c,environment='test'))
    if defect=='unknown_profile': rows=(a,b,replace(c,case_profile='new'))
    if defect=='wrong_adapter': rows=(a,b,replace(c,adapter_version='rf1086-production-v1'))
    if defect=='malformed_id': rows=(a,b,replace(c,id='not-a-uuid'))
    if defect=='unknown_parent': rows=(a,b,replace(c,supersedes_submission_id=str(UUID(int=9))))
    if defect=='feedback_mismatch': rows=(a,b,replace(c,feedback_state='processing'))
    if defect=='uncertain_ancestor': rows=(replace(a,status='unknown'),b,c)
    with pytest.raises(rf.Rf1086ProductionError): check(rows, prior(c))


@pytest.mark.parametrize('rows', [None, [], ({},)])
def test_missing_or_untyped_enumeration_is_not_an_empty_history(rows):
    with pytest.raises(rf.Rf1086ProductionError): check(rows, None)


@pytest.mark.parametrize('defect', ['competing_root','new_child','different_owner_root','unknown_head'])
def test_correction_approval_rechecks_history_inside_guard_before_parent_lock_or_write(defect):
    h=CorrectionHarness(); row=h.history[0]
    if defect=='competing_root': h.history+=(replace(row,id=str(UUID(int=1100))),)
    if defect=='new_child': h.history+=(replace(row,id=str(UUID(int=1100)),supersedes_submission_id=row.id),)
    if defect=='different_owner_root': h.history+=(replace(row,id=str(UUID(int=1100)),user_id=str(UUID(int=1101))),)
    if defect=='unknown_head': h.history=(replace(row,status='unknown',feedback_state='unknown'),)
    with pytest.raises(rf.Rf1086ProductionError): h.approve(predecessor=h.prior)
    assert h.calls.index('guard') < h.calls.index('history') < h.calls.index('release')
    assert not h.writes and not h.committed and 'prior_lock' not in h.calls


def test_initial_approval_cannot_ignore_an_existing_company_year_filing():
    h=ApprovalHarness(); h.history=(predecessor_snapshot().submission,)
    with pytest.raises(rf.Rf1086ProductionError): h.approve()
    assert 'history' in h.calls and not h.writes and not h.committed


def test_matching_correction_keeps_original_byte_and_manifest_checks():
    h=CorrectionHarness(); h.approve(predecessor=h.prior)
    assert h.calls.index('history') < h.calls.index('prior_lock') < h.calls.index('review') < h.calls.index('append')
    assert h.committed
