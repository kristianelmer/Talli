"""Finite, preparation-only admission for the approved existing synthetic company."""
from datetime import datetime, UTC

from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.modules.company_access.public import CompanyAccessError
from talli_backend.modules.company_tax_filing.public import CompanyTaxError
from talli_backend.shared.kernel import ActorKind

COMPANY = '53454096-3fb6-45a6-a9c8-35fa83824614'
OWNER = '8ca24df3-12af-4be0-a534-4a26092c97bc'
ORGANIZATION = '992803750'


class PrivatePreviewTaxPreparation(CompanyTaxDeliveryPreparation):
    preparation_only = True

    def __init__(self, current, schemas, access, token, expires_at, *, now=None):
        super().__init__(current, schemas)
        self._access, self._token = access, token
        self._expires_at = expires_at
        self._clock = now or (lambda: datetime.now(UTC))

    def _scope(self, session, company, year):
        return (session.actor_id.kind is ActorKind.USER and str(session.actor_id.subject) == OWNER and str(company) == COMPANY
                and int(year) == 2025 and self._clock() < self._expires_at)

    async def authorize(self, session, query):
        if query.actor_id != session.actor_id or not self._scope(session, query.company_id, query.income_year):
            raise CompanyTaxError.forbidden()
        try:
            context = (await self._access.selected_context(self._token,
                company_id=COMPANY, accounting_year=2025)).selected_company
        except CompanyAccessError:
            raise CompanyTaxError.forbidden() from None
        if (not self._scope(session, query.company_id, query.income_year)
                or context.id != COMPANY or context.org_number != ORGANIZATION
                or context.source != 'browser_test' or context.created_by != OWNER
                or context.name != 'Synthetic private Preview 714f7b19'
                or context.entity_type != 'AS' or context.status_text != 'aktiv'
                or context.address != 'Disposable private Preview synthetic fixture'
                or context.postal_code != '0155' or context.city != 'OSLO'
                or not context.identity_confirmed_at or not context.identity_locked_at
                or context.role != 'owner' or context.aal != 'aal2'
                or not context.current_agreement_accepted or context.company_year_admission_id is None
                or context.admitted_accounting_year != 2025 or context.current_eligibility_decision != 'supported'
                or not context.consequential_operations_allowed):
            raise CompanyTaxError.forbidden()

    def workspace_admission(self, session, source, parent=None):
        return (parent is None and self._scope(session, source.company_id, source.income_year)
                and source.organization_number == ORGANIZATION)
