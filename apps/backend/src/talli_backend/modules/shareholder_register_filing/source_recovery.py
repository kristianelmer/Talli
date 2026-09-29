"""Recover confirmed source submissions from retained commitments, never live facts."""
import json
from uuid import UUID

from talli_backend.shared.kernel import ActorKind
from . import public as rf


def prepare(archive, *, query, submission, forsendelse_id, dialog_id):
    """Bind read-only feedback to a complete claim, original payload and journal.

    Archive validation rebuilds the approved source manifest and checks every
    POST hash and confirmation against its journal. It does not demand today's
    source head, current approval eligibility or an unexpired pilot.
    """
    try:
        if not isinstance(query, rf.Rf1086ArchiveQuery):
            raise ValueError()
        if (not isinstance(submission, rf.Rf1086Submission)
                or submission.case_profile != 'rf1086_full_year_v1'
                or query.actor_id.kind is not ActorKind.USER
                or submission.user_id != str(query.actor_id.subject)):
            raise ValueError()
        assessment = rf.assess_rf1086_source_dispatch(archive, query=query,
            submission_id=rf.SubmissionId(submission.id))
        if assessment.disposition != 'confirmed':
            raise ValueError()
        retained = next(row for row in archive.production_submissions if row.id == submission.id)
        for field in ('id', 'approval_id', 'entitlement_id', 'company_id', 'user_id',
                      'income_year', 'obligation', 'case_profile', 'environment'):
            if getattr(retained, field) != getattr(submission, field):
                raise ValueError()
        for reference in (forsendelse_id, dialog_id):
            if type(reference) is not str or str(UUID(reference)) != reference:
                raise ValueError()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        confirmation = json.loads(retained.authority_references['confirm'], object_pairs_hook=unique)
        if confirmation != {'dialogId': dialog_id, 'forsendelseId': forsendelse_id}:
            raise ValueError()
        approval = next(row for row in archive.approvals if row.id == retained.approval_id)
        # The archive validator proves this bridge uses the exact source_* keys
        # and XML from the source manifest, including every stable shareholder ID.
        return rf.Rf1086ReconciliationInput(retained.id, retained.company_id, retained.income_year,
            forsendelse_id, assessment.payload.hovedskjema_xml, assessment.payload.underskjema_xml,
            approval.manifest['organizationNumber'], dialog_id)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration,
            rf.ShareholderRegisterFilingError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
