"""Durable bank-consent, recovery, and revocation orchestration."""

from __future__ import annotations

from talli_backend.modules.banking.public import (
    BankConnection,
    BankConnectionPersistence,
    BankConsentRedirect,
    BankDataProvider,
    BankingError,
    BankingErrorCode,
    BeginBankConsentRequest,
    CompleteBankConnectionCommand,
    CompleteBankConsentRequest,
    RevokeBankConnectionCommand,
    RevokeBankConsentRequest,
    StartBankConnectionCommand,
)


class BankingConsentWorkflow:
    def __init__(
        self,
        persistence: BankConnectionPersistence,
        provider: BankDataProvider,
    ) -> None:
        self._persistence = persistence
        self._provider = provider

    async def start(self, command: StartBankConnectionCommand) -> BankConsentRedirect:
        if command.connector_id != self._provider.connector_id:
            raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        await self._persistence.begin_connection(command)
        try:
            redirect = await self._provider.begin_consent(
                BeginBankConsentRequest(
                    connection_id=command.connection_id,
                    company_id=command.company_id,
                    connector_id=command.connector_id,
                    bank_key=command.bank_key,
                    return_url=command.return_url,
                )
            )
        except BankingError as error:
            await self._persistence.fail_connection(command, error_code=error.code)
            raise
        return await self._persistence.record_consent_redirect(command, redirect)

    async def complete(self, command: CompleteBankConnectionCommand) -> BankConnection:
        replay = await self._persistence.get_connection_completion_replay(command)
        if replay is not None:
            if replay.connector_id != self._provider.connector_id:
                raise BankingError.invalid_input(
                    BankingErrorCode.PROVIDER_RESPONSE_INVALID
                )
            return replay
        try:
            provider_connection = await self._provider.complete_consent(
                CompleteBankConsentRequest(
                    connection_id=command.connection_id,
                    company_id=command.company_id,
                    callback_parameters=command.callback_parameters,
                )
            )
        except BankingError as error:
            await self._persistence.fail_connection(command, error_code=error.code)
            raise
        if provider_connection.connector_id != self._provider.connector_id:
            await self._persistence.fail_connection(
                command,
                error_code=BankingErrorCode.PROVIDER_RESPONSE_INVALID.value,
            )
            raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        return await self._persistence.complete_connection(command, provider_connection)

    async def revoke(self, command: RevokeBankConnectionCommand) -> None:
        adapter_connection_reference = await self._persistence.begin_revocation(command)
        await self._provider.revoke_consent(
            RevokeBankConsentRequest(
                connection_id=command.connection_id,
                company_id=command.company_id,
                adapter_connection_reference=adapter_connection_reference,
            )
        )
        await self._persistence.complete_revocation(command)


__all__ = ["BankingConsentWorkflow"]
