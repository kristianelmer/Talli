"""Prepare read-only recovery from original confirmed retained evidence."""
from . import public as rf
from .source_recovery import _prepare


def prepare(archive, *, query, submission, forsendelse_id, dialog_id):
    """Preserve original references and XML, including a confirmed ancestor.

    This pure value does not acquire a lease, establish current owner access or
    authorize a provider call. No current renderer or fresh-source query runs.
    """
    try:
        return _prepare(archive, query=query, submission=submission,
            forsendelse_id=forsendelse_id, dialog_id=dialog_id,
            assess_dispatch=rf.assess_rf1086_retained_source_dispatch)
    except RecursionError:
        raise rf.Rf1086ProductionError('basis_unavailable') from None
