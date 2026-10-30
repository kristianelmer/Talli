"""Compose complete Accounts owning facts in one verified repeatable snapshot."""
from typing import Protocol

from talli_backend.application.annual_data_compatibility import decode_annual_interview_history
from talli_backend.application.corporate_governance_session import CorporateGovernanceWorkflowTransaction
from talli_backend.application.corporate_governance_workflow import CorporateGovernanceApplication
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsDeliverySource, AnnualAccountsError, AnnualAccountsSourceQuery, annual_accounts_delivery_digest,
)
from talli_backend.modules.corporate_governance.public import CorporateDecisionKind, CorporateGovernanceError
from talli_backend.modules.ledger.public import LedgerQueries, LedgerError, read_ledger_reporting_snapshot
from talli_backend.shared.kernel import ActorId, CorrelationId


class AnnualAccountsDeliverySourceInputs(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    @property
    def delivery_ledger_queries(self) -> LedgerQueries: ...
    @property
    def delivery_corporate_queries(self) -> CorporateGovernanceWorkflowTransaction: ...
    async def delivery_annual_interview_history(self, query: AnnualAccountsSourceQuery) -> list[object]: ...


async def read_annual_accounts_delivery_source(inputs: AnnualAccountsDeliverySourceInputs,
        query: AnnualAccountsSourceQuery, *, corporate: CorporateGovernanceApplication,
        correlation_id: CorrelationId) -> AnnualAccountsDeliverySource:
    if inputs.actor_id!=query.actor_id:raise AnnualAccountsError.forbidden()
    try:
        corporate_queries=inputs.delivery_corporate_queries
        readiness,lifecycle=await corporate.read_readiness_in_transaction(corporate_queries,
            actor_id=query.actor_id,company_id=query.company_id,income_year=query.income_year,
            decision_kind=CorporateDecisionKind.ANNUAL_CLOSE,correlation_id=correlation_id)
        company=await corporate_queries.read_company_facts(query.company_id)
        history=await inputs.delivery_annual_interview_history(query)
        if type(history) is not list or len(history)>101:raise ValueError('Annual history exceeds the supported year extent.')
        annual=decode_annual_interview_history(history,query.company_id,query.income_year)
        if (annual is None or company.company_id!=query.company_id or readiness.company_id!=query.company_id
                or readiness.income_year!=query.income_year):raise ValueError('Accounts owning source scope differs.')
        # The compatibility decoder maps missing workforce to zero for its old
        # consumers. Accounts must retain the original missing fact and block it.
        current=next(item for item in history if item['sourceId']==annual.source_id)
        annual_data={'id':annual.source_id,'company_id':str(query.company_id),'income_year':int(query.income_year),
            'answers':annual.answers,'confirmations':annual.confirmations,'no_activity_confirmed':annual.no_activity_confirmed,
            'annual_full_time_equivalents':current['annualFullTimeEquivalents'],
            'completed_at':annual.completed_at,'updated_at':annual.updated_at}
        ledger=await read_ledger_reporting_snapshot(inputs.delivery_ledger_queries,actor_id=query.actor_id,
            company_id=query.company_id,income_year=query.income_year,correlation_id=correlation_id)
        entries=tuple({'id':str(row.entry_id),'company_id':str(row.company_id),'income_year':int(row.income_year),
            'entry_type':row.entry_kind.value,'memo':row.memo,
            'lines':tuple({'account':line.account,'description':line.description,'debit':format(line.debit.amount,'f'),
                'credit':format(line.credit.amount,'f'),'currency':line.debit.currency.value} for line in row.lines),
            'risk_flags':tuple(flag.code.value for flag in row.risk_flags),
            'warning_accepted_at':row.warning_accepted_at.value.isoformat() if row.warning_accepted_at else None}
            for row in ledger.effective_entries)
        snapshots={'annual':history,'ledger':ledger,'corporate':{'readiness':readiness,'snapshot':lifecycle}}
        return AnnualAccountsDeliverySource(query.company_id,query.income_year,company.organization_number,company.legal_name,
            annual_data,entries,snapshots,{name:annual_accounts_delivery_digest(value) for name,value in snapshots.items()})
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError,LedgerError,CorporateGovernanceError):
        raise AnnualAccountsError.unavailable() from None
