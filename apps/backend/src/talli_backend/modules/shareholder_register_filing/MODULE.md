# Shareholder-register filing contract shell

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":[],"publicEntryPoints":["talli_backend.modules.shareholder_register_filing.public"]}
-->

## Current boundary

This module declares only the future capability's opening-snapshot public
contract so the backend-system `new-year-start` workflow can coordinate it with
`ledger` without assigning shareholder facts to ledger. It owns no schema,
table, filing rule, submission path, or statutory artifact during #139.

The one canonical implementation remains the frozen legacy
`public.opening_balance_setups` and `public.opening_shareholders` persistence,
reached through an application-layer compatibility adapter inside the
coordinator's existing PostgreSQL transaction. Stage #151 must migrate that
implementation and remove the compatibility shell. No bank balance, ledger
account, line, memo, or posting policy is accepted by this contract.

## Public interface

`RecordOpeningSnapshotCommand` carries the frozen opening facts and a tuple of
validated `OpeningShareholder` values plus company, actor, correlation, and
idempotency identities. `ShareholderRegisterFilingCommands` exposes the single
command, which returns an `OpeningSnapshotId`. Expected failures use
`ShareholderRegisterFilingError` and the closed
`ShareholderRegisterFilingErrorCode` values. The concrete compatibility
implementation is outside this public package.
