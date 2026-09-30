"""Select a correction parent from the complete company/year filing history.

Timestamps cannot resolve competing roots, forks or incomplete history. The
caller must enumerate under its company/year guards and keep them until write.
This check does not verify feedback bytes or authorize a provider operation.
"""
from uuid import UUID

from . import public as rf


def assert_predecessor(history, *, company_id, income_year, predecessor):
    def require(condition):
        if not condition:
            raise rf.Rf1086ProductionError('basis_unavailable')

    try:
        require(type(history) is tuple)
        rows = {}
        children = {}
        profiles = {'rf1086_no_activity_v1': 'rf1086-production-v1',
                    'rf1086_full_year_v1': 'rf1086-source-production-v1'}
        for row in history:
            require(isinstance(row, rf.Rf1086ProductionSubmissionRecord))
            require(type(row.id) is str and str(UUID(row.id)) == row.id and row.id not in rows)
            require(row.company_id == str(company_id) and type(row.income_year) is int
                    and row.income_year == int(income_year)
                    and row.obligation == 'aksjonaerregisteroppgaven' and row.environment == 'production'
                    and row.case_profile in profiles and row.adapter_version == profiles[row.case_profile])
            rows[row.id] = row
            parent = row.supersedes_submission_id
            if parent is not None:
                require(type(parent) is str and str(UUID(parent)) == parent
                        and parent != row.id and parent not in children)
                children[parent] = row.id
        require(all(parent in rows for parent in children))
        if not rows:
            require(predecessor is None)
            return
        roots = [row.id for row in history if row.supersedes_submission_id is None]
        require(len(roots) == 1)
        visited = set()
        head_id = roots[0]
        while True:
            require(head_id not in visited)
            visited.add(head_id)
            if head_id not in children:
                break
            # A correction cannot resolve an uncertain predecessor by merely
            # adding another row. Historical ancestors must also be terminal.
            parent = rows[head_id]
            require(parent.status in ('accepted', 'rejected') and parent.feedback_state == parent.status)
            head_id = children[head_id]
        require(len(visited) == len(rows))
        head = rows[head_id]
        require(isinstance(predecessor, rf.Rf1086SourceCorrectionPredecessor)
                and isinstance(predecessor.submission_id, rf.SubmissionId)
                and predecessor.submission_id.value == head_id
                and head.status in ('accepted', 'rejected') and head.feedback_state == head.status)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
