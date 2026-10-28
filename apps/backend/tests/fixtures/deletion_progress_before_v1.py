"""Frozen local-progress formats from7cf9d060/46e8a357; not a purge adapter."""
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DocumentDisposition:
    operation_id: UUID
    company_id: UUID
    document_id: UUID
    income_year: int
    generation: str
    content_sha256: str
    company_generation: str
    plan_sha256: str


def receipt_7cf(command):
    old = DocumentDisposition(command.operation_id,command.company_id,command.document_id,
        command.income_year,command.generation,command.content_sha256,command.company_generation,command.plan_sha256)
    return sha256((repr(old)+':'+command.action).encode()).hexdigest()


def receipt_46e(command):
    # The46e repr adds a final action field; no other field changed.
    old = DocumentDisposition(command.operation_id,command.company_id,command.document_id,
        command.income_year,command.generation,command.content_sha256,command.company_generation,command.plan_sha256)
    return sha256((repr(old)[:-1]+', action='+repr(command.action)+')').encode()).hexdigest()
