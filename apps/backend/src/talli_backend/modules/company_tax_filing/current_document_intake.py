"""Server-derived scope for a current-document read before a draft exists."""
from dataclasses import dataclass
import re

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,CorrelationId,UserId
from .delivery import _digest


@dataclass(frozen=True,slots=True)
class TaxCurrentDocumentIntakeQuery:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    organization_number: str
    database_scope_sha256: str
    correlation_id: CorrelationId

    def __post_init__(self):
        _digest(self.database_scope_sha256)
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year)!=2025
                or type(self.actor_id) is not ActorId or self.actor_id.kind is not ActorKind.USER
                or type(self.actor_id.subject) is not UserId or type(self.correlation_id) is not CorrelationId
                or type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None):
            raise ValueError('Tax current-document intake scope is invalid.')
