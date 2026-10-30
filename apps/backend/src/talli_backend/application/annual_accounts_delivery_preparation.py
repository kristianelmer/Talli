"""Guarded Accounts preparation from current owning facts, with exact replay."""
from talli_backend.application.annual_accounts_delivery_source import read_annual_accounts_delivery_source
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError, AnnualAccountsSourceQuery, PrepareAnnualAccountsDeliveryDraft,
    StoredAnnualAccountsDeliveryDraft, prepare_annual_accounts_delivery, project_annual_accounts_source,
)


class AnnualAccountsDeliveryPreparation:
    def __init__(self,corporate,schemas):self._corporate,self._schemas=corporate,schemas

    async def prepare(self,session,command: PrepareAnnualAccountsDeliveryDraft) -> StoredAnnualAccountsDeliveryDraft:
        if session.actor_id!=command.actor_id:raise AnnualAccountsError.forbidden()
        query=AnnualAccountsSourceQuery(command.company_id,command.income_year,command.actor_id)
        # Replay remains available after a write shutdown or source change.
        # The owner/MFA-protected RPC reads the exact committed original first.
        async with session.transaction() as transaction:
            stored=await transaction.delivery_draft_by_key(query,command.command_key)
            if stored is not None:return self._replayed(stored,command)
            await transaction.lock_delivery_archive(query)
            # Every owning mutation participates in the published company
            # archive guard. The independent RR snapshot starts after acquiring
            # that guard; no source-changing write can pass before this commit.
            async with session.transaction(snapshot=True) as snapshot:
                history=await snapshot.filing_source_snapshot(query)
                facts=project_annual_accounts_source(query,history)
                if (history.contract_version not in ('annual-accounts-source-v2','annual-accounts-source-v3','annual-accounts-source-v4')
                        or facts.history_coverage.status!='complete'):raise AnnualAccountsError.unavailable()
                source=await read_annual_accounts_delivery_source(snapshot,query,corporate=self._corporate,
                    correlation_id=command.correlation_id)
            draft=prepare_annual_accounts_delivery(source,filing_id=str(command.filing_id),command_key=command.command_key,
                actor_id=command.actor_id,contact_email=command.contact_email,
                confirming_representative=command.confirming_representative,schemas=self._schemas)
            # Check a concurrent replay and clock-based MFA again after the
            # bounded source read and local schema compilation/validation.
            await transaction.lock_delivery_archive(query)
            stored=await transaction.delivery_draft_by_key(query,command.command_key)
            if stored is not None:return self._replayed(stored,command)
            stored=await transaction.store_delivery_draft(draft)
            if stored.draft!=draft:raise AnnualAccountsError.unavailable()
            return stored

    @staticmethod
    def _replayed(stored,command):
        draft=stored.draft
        if (draft.prepared_by!=command.actor_id or draft.source.company_id!=command.company_id
                or draft.source.income_year!=command.income_year or draft.command_key!=command.command_key):
            raise AnnualAccountsError.unavailable()
        if (draft.filing_id!=str(command.filing_id) or draft.contact_email!=command.contact_email
                or draft.confirming_representative!=command.confirming_representative):raise AnnualAccountsError.draft_conflict()
        return stored
