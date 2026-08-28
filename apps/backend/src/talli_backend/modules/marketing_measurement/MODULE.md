# Marketing measurement backend technical module

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":["MarketingMeasurementGateway"],"publicEntryPoints":["talli_backend.modules.marketing_measurement.public"]}
-->

## Purpose

This backend-system technical module owns one consent-bounded, provider-neutral
measurement contract. It is not a business capability and cannot decide
eligibility, billing, acquisition spend, launch clearance, or product behavior.

## Backend-system technical state

The backend system, not this representative module, owns
`backend_system.marketing_funnel_events`. It contains only a client event UUID, an
irreversible anonymous-session SHA-256 hash, exact consent version, bounded
event/reason/surface/source codes, server receive time, and deletion deadline.
The raw table is forced-RLS, retained for at most 90 days, and unavailable to
browser, Data API, authenticated, service, ingest, and report roles.

## Public interface and port

Import only `talli_backend.modules.marketing_measurement.public`. The public
contract exposes `MarketingMeasurementEvent`, aggregate-only
`MarketingFunnelReport` and `MarketingRepeatedSignal`, stable
`MarketingMeasurementError`, and `MarketingMeasurementGateway`.
`marketing_measurement_adapter` binds the port to the restricted PostgreSQL
adapter selected by backend composition.

## Privacy and authority boundary

The ingest function accepts no person, company, financial, URL, IP, user-agent,
client timestamp, arbitrary campaign value, JSON payload, or free text. A raw
session closes after 30 minutes. Withdrawal deletes its raw rows. The report
requires a separately verified active operator and returns only aggregates;
acquisition cost remains unavailable until approved spend exists.

## Change rule

Change this document and `module.json` together whenever the public contract,
port, owned technical table, migration, dependency, or forbidden responsibility
changes. No compatibility exception is authorized.
