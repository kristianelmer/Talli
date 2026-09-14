"""Audit's immutable append contract over its single legacy implementation.

This shell does not migrate Audit tables, retention, queries, or producer policy.
The initiating application workflow owns transaction scope and replay ordering.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from talli_backend.shared.kernel import ActorId, CompanyId


@dataclass(frozen=True, slots=True)
class AuditEventDraft:
    company_id: CompanyId
    actor_id: ActorId
    category: str
    action: str
    message: str


class AuditInclusion(Protocol):
    async def include_audit_event(self, event: AuditEventDraft) -> None:
        """Append through the canonical legacy store in the caller's transaction."""
        ...


Adapter = TypeVar('Adapter', bound=type[object])


def audit_inclusion_adapter(contract: type[object]) -> Callable[[Adapter], Adapter]:
    def declare(adapter: Adapter) -> Adapter:
        _ = contract
        return adapter
    return declare


__all__ = ['AuditEventDraft', 'AuditInclusion', 'audit_inclusion_adapter']
