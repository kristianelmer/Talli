"""Authenticated Accounts workflows consume only capability-owned public ports."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from talli_backend.application.annual_accounts_session import AnnualAccountsSession, AnnualAccountsSessionFactory
from talli_backend.modules.annual_accounts_filing.public import (
    ImportAnnualAccountsEvidence, ImportedAnnualAccountsEvidence, AnnualAccountsEvidenceInput, import_annual_accounts_evidence,
    AnnualAccountsRecordQuery, RecordAnnualAccountsOverride, AddAnnualAccountsReviewComment,
    ConfirmAnnualAccountsPermission, RecordAnnualAccountsTestEvidence, AnnualAccountsRecordedResult,
    normalize_annual_accounts_override, normalize_annual_accounts_review, normalize_annual_accounts_test_evidence,
    AnnualAccountsError, AnnualAccountsFilingRows, AnnualAccountsWorkspaceQuery,
    AnnualAccountsSourceQuery, AnnualAccountsSourceEvidence, AnnualAccountsSourceFacts, project_annual_accounts_source, verify_annual_accounts_source,
)


class AnnualAccountsApplication:
    def __init__(self, sessions: AnnualAccountsSessionFactory):
        self._sessions = sessions

    async def session(self, access_token: str) -> AuthenticatedAnnualAccounts:
        return AuthenticatedAnnualAccounts(await self._sessions.session(access_token))


class AuthenticatedAnnualAccounts:
    def __init__(self, session: AnnualAccountsSession):
        self._session = session

    @property
    def actor_id(self):
        return self._session.actor_id

    async def filing_workspace(self, query: AnnualAccountsWorkspaceQuery) -> AnnualAccountsFilingRows:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        async with self._session.transaction() as transaction:
            result = await transaction.filing_workspace(query)
            if result.company_id != query.company_id or result.income_year != query.income_year:
                raise AnnualAccountsError.unavailable()
            return result

    async def filing_source_facts(self, query: AnnualAccountsSourceQuery) -> AnnualAccountsSourceFacts:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        async with self._session.transaction(snapshot=True) as transaction:
            return project_annual_accounts_source(query, await transaction.filing_source_snapshot(query))

    async def verify_filing_source(self, query: AnnualAccountsSourceQuery, evidence: AnnualAccountsSourceEvidence) -> bool:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        async with self._session.transaction(snapshot=True) as transaction:
            return verify_annual_accounts_source(query, evidence, await transaction.filing_source_snapshot(query))

    async def filing_preview(self, query: AnnualAccountsRecordQuery) -> Mapping[str, object] | None:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        async with self._session.transaction() as transaction:
            return await transaction.filing_preview(query)

    async def record_override(self, command: RecordAnnualAccountsOverride) -> AnnualAccountsRecordedResult:
        if command.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        normalized = normalize_annual_accounts_override(command)
        async with self._session.transaction() as transaction:
            return await transaction.record_override(normalized)

    async def add_review_comment(self, command: AddAnnualAccountsReviewComment) -> AnnualAccountsRecordedResult:
        if command.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        normalized = normalize_annual_accounts_review(command)
        async with self._session.transaction() as transaction:
            return await transaction.add_review_comment(normalized)

    async def acknowledge_review_comment(self, query: AnnualAccountsRecordQuery) -> AnnualAccountsRecordedResult:
        if query.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        async with self._session.transaction() as transaction:
            result = await transaction.acknowledge_review_comment(query)
            if result.record_id != query.record_id:
                raise AnnualAccountsError.unavailable()
            return result

    async def confirm_filing_permission(self, command: ConfirmAnnualAccountsPermission) -> AnnualAccountsRecordedResult:
        if command.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        if type(command.production_enabled) is not bool:
            raise AnnualAccountsError.invalid_input()
        async with self._session.transaction() as transaction:
            result = await transaction.confirm_filing_permission(command)
            if result.company_id != command.company_id or result.income_year is not None:
                raise AnnualAccountsError.unavailable()
            return result

    async def record_test_evidence(self, command: RecordAnnualAccountsTestEvidence) -> AnnualAccountsRecordedResult:
        if command.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        normalized = normalize_annual_accounts_test_evidence(command)
        async with self._session.transaction() as transaction:
            result = await transaction.record_test_evidence(normalized)
            if result.company_id != command.company_id or result.income_year is not None:
                raise AnnualAccountsError.unavailable()
            return result

    async def import_tt02_evidence(self, command: ImportAnnualAccountsEvidence) -> ImportedAnnualAccountsEvidence:
        if command.actor_id != self.actor_id:
            raise AnnualAccountsError.forbidden()
        async with self._session.transaction() as transaction:
            company = await transaction.filing_company_identity(command.company_id, command.actor_id)
            if company.company_id != command.company_id:
                raise AnnualAccountsError.unavailable()
            try:
                projection = import_annual_accounts_evidence(AnnualAccountsEvidenceInput(
                    company_id=str(command.company_id), expected_organization_number=company.organization_number,
                    evidence=command.evidence, recorded_by=str(command.actor_id.subject),
                    recorded_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                    evidence_url=command.evidence_url,
                ))
            except ValueError as error:
                raise AnnualAccountsError.invalid_input(str(error)) from None
            record_id = await transaction.import_tt02_evidence(projection, command.actor_id)
            return ImportedAnnualAccountsEvidence(record_id, projection.test_reference)
