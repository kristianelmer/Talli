# Validation observation backend technical module

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":["ValidationObservationGateway"],"publicEntryPoints":["talli_backend.modules.validation_observation.public"]}
-->

## Purpose

This technical module owns the only product-facing interface for invited-pilot
observation. The interface is passive, server configured, deny-by-default and
side-effect-only. It can never unlock, block, alter, retry, replace or simulate a
normal product action.

## Contract

`PassiveValidationObserver.after_outcome` accepts a transient server-known
subject identifier and a `BoundedValidationObservation` only after the normal
outcome settles. It returns no receipt or status. Off mode performs no gateway
call. Invited mode creates a keyed subject digest and sends one command to the
restricted persistence port under a strict deadline; every writer error is
contained. Missing evidence therefore blocks validation completeness, not the
product outcome.

The port command is `AuthorizedValidationObservation`; storage failures are
represented only inside the boundary as `ValidationObservationError`.
`validation_observation_adapter` records the selected implementation for
architecture verification.

The command has no identity, organization number, contact, free text, document,
bank, ledger, monetary, URL, user-agent, IP, or marketing-attribution field. The
database derives the protected `V-01` through `V-12` case code only after it
atomically validates the run, entitlement, subject binding, release, participant
information, start, expiry, revocation and withdrawal state.

## Activation boundary

Environment values may request observation but never grant authority. Exact
`invited-pilot` plus exact `prelaunch-validation`, a short local time window and
complete server binding are necessary but insufficient. The database remains
authoritative. No run or entitlement is provisioned by application startup or
migration. Participant information, retention, reviewers and protected mapping
remain human/legal entry gates.

The selected adapter is
`talli_backend.adapters.supabase_validation_observation.SupabaseValidationObservationAdapter`.
It has only the `validation_observation_writer_executor` SET-role path and calls
one typed private PostgreSQL function. It cannot provision, review, revoke,
withdraw, change mode or evaluate launch readiness.

## Change rule

Change this document and `module.json` together whenever the public contract,
port, technical state, migration or forbidden responsibility changes.
