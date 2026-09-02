"""Frozen shareholder-register implementation used only by new-year coordination."""

from __future__ import annotations

from talli_backend.application.ledger_session import LedgerWorkflowTransaction
from talli_backend.modules.ledger.public import LedgerError
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
    ShareholderRegisterFilingError,
)
from talli_backend.shared.kernel import Money


class LegacyShareholderRegisterFilingFacade:
    """Translate two owned intents into the one frozen combined legacy table."""

    def __init__(
        self,
        transaction: LedgerWorkflowTransaction,
        ledger_bank_balance: Money,
    ) -> None:
        self._transaction = transaction
        self._ledger_bank_balance = ledger_bank_balance

    async def record_opening_snapshot(
        self, command: RecordOpeningSnapshotCommand
    ) -> OpeningSnapshotId:
        if command.actor_id != self._transaction.actor_id:
            raise ShareholderRegisterFilingError.forbidden()
        try:
            return await self._transaction.record_legacy_opening_snapshot(
                command,
                ledger_bank_balance=self._ledger_bank_balance,
            )
        except ShareholderRegisterFilingError:
            raise
        except LedgerError as error:
            translations = {
                "LEDGER_INVALID_INPUT": ShareholderRegisterFilingError.invalid_input,
                "LEDGER_NOT_FOUND": ShareholderRegisterFilingError.not_found,
                "LEDGER_FORBIDDEN": ShareholderRegisterFilingError.forbidden,
                "LEDGER_COMPANY_YEAR_NOT_ADMITTED": (
                    ShareholderRegisterFilingError.company_year_not_admitted
                ),
                "LEDGER_OPENING_ALREADY_EXISTS": (
                    ShareholderRegisterFilingError.opening_already_exists
                ),
                "LEDGER_DEPENDENCY_UNAVAILABLE": (
                    ShareholderRegisterFilingError.unavailable
                ),
            }
            factory = translations.get(error.code)
            if factory is None:
                raise ShareholderRegisterFilingError.unavailable() from None
            raise factory() from None
        except ValueError:
            raise ShareholderRegisterFilingError.unavailable() from None


__all__ = ["LegacyShareholderRegisterFilingFacade"]
