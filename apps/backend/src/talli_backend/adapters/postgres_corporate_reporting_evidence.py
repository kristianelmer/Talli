"""Complete Governance evidence through public projections on a guarded connection."""
from collections.abc import Mapping

import psycopg
from psycopg.pq import TransactionStatus

from talli_backend.adapters.supabase_corporate_governance import (
    _lifecycle_snapshot, _recorded_supported_event,
)
from talli_backend.adapters.supabase_ledger import _actor, _timestamp
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference, CorporateGovernanceError, CorporateGovernanceYearEvidence,
    CorporateLedgerAmendment, CorporateReportingYearBasis, build_reporting_year_evidence,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


class PostgresCorporateReportingEvidence:
    """Requires the caller's existing READ COMMITTED, company-guarded transaction.

    Never opens a connection, changes roles/identity, acquires a different company
    guard, or performs provider I/O. SQL independently checks the live owner and
    existing guard; the public domain builder validates complete scoped inputs.
    """
    def __init__(self, connection, actor_id: ActorId):
        self._connection = connection
        self._actor_id = actor_id

    async def read_reporting_year_evidence(self, *, company_id: CompanyId,
            income_year: IncomeYear, correlation_id: CorrelationId) -> CorporateGovernanceYearEvidence:
        if self._connection.info.transaction_status != TransactionStatus.INTRANS:
            raise CorporateGovernanceError.unavailable()
        try:
            row = await (await self._connection.execute(
                'select corporate_governance.read_guarded_reporting_year_inputs_v1(%s::uuid,%s::integer,%s::text) as result',
                (str(company_id), int(income_year), str(self._actor_id.subject)),
            )).fetchone()
            value = row['result'] if row else None
            if (not isinstance(value, Mapping) or value.get('companyId') != str(company_id)
                    or type(value.get('incomeYear')) is not int or value['incomeYear'] != int(income_year)
                    or not isinstance(value.get('lifecycle'), Mapping)
                    or not isinstance(value.get('supportedEvents'), list)
                    or not isinstance(value.get('amendments'), list)
                    or not all(isinstance(item, Mapping) for item in value['supportedEvents'] + value['amendments'])):
                raise CorporateGovernanceError.unavailable()
            basis = CorporateReportingYearBasis(company_id, _lifecycle_snapshot(value['lifecycle']),
                tuple(_recorded_supported_event(item) for item in value['supportedEvents']))
            amendments = tuple(CorporateLedgerAmendment(
                AccountingEntryReference(str(item['original_entry_id'])),
                AccountingEntryReference(str(item['reversal_entry_id'])),
                AccountingEntryReference(str(item['replacement_entry_id'])) if item['replacement_entry_id'] is not None else None,
                CompanyId(str(item['company_id'])), IncomeYear(item['income_year']), item['reason'],
                _actor(item['amended_by']), _timestamp(item['amended_at']).value,
            ) for item in value['amendments'])
            return build_reporting_year_evidence(basis=basis, income_year=income_year, amendments=amendments)
        except psycopg.DatabaseError as error:
            if 'corporate_governance_forbidden' in str(error) or 'ledger_forbidden' in str(error):
                raise CorporateGovernanceError.forbidden() from None
            raise CorporateGovernanceError.unavailable() from None
        except (KeyError, TypeError, ValueError, AttributeError):
            raise CorporateGovernanceError.unavailable() from None
