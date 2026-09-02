# Marketing measurement backend technical module

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":["MarketingMeasurementGateway"],"publicEntryPoints":["talli_backend.modules.marketing_measurement.public"]}
-->

## Purpose

This backend-system technical module owns one consent-proof, provider-neutral
public-session measurement contract. It is not a business capability and cannot decide
eligibility, billing, acquisition spend, launch clearance, or product behavior.

## Backend-system technical state

The backend system, not this representative module, owns
`backend_system.marketing_funnel_events`. It contains only a client event UUID, an
irreversible random-session SHA-256 hash, exact consent and notice/release
binding, bounded event/reason/surface/source codes, server receive time, and
deletion deadline. A separate forced-RLS action journal proves the server receive
time of grant or withdrawal. A release table is empty by default and can be
populated only through the separate provisioner role after human approval.
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

The ingest function accepts no person, account, company, purchase, financial,
document, support, refund, filing, URL, IP, user-agent, client timestamp,
arbitrary campaign value, JSON payload, or free text. A raw session closes 30
minutes after the server-stamped grant. Withdrawal deletes its raw rows. The report
requires a separately verified active operator and returns only aggregates;
repeated signals require five distinct sessions. Acquisition cost and every
longitudinal outcome remain unavailable.

## Change rule

Change this document and `module.json` together whenever the public contract,
port, owned technical table, migration, dependency, or forbidden responsibility
changes. No compatibility exception is authorized.
