# System boundary backend technical module

<!-- architecture-inventory
{"dependencies":[],"ownedTables":[],"ports":["SystemBoundaryTransport"],"publicEntryPoints":["talli_backend.modules.system_boundary.public"]}
-->

## Purpose

This module owns Talli's deterministic boundary-availability contract. It is a
technical representative module only: it owns no business rule, business table,
provider operation, or authoritative write.
Its manifest kind is `backend-technical-module`, so it is part of the backend
system and is not one of ADR-0011's business capabilities.

## Owns and must not own

It owns the `SYSTEM_BOUNDARY_AVAILABLE` public contract and the
`SystemBoundaryTransport` port. It owns no Postgres schema, table, bucket,
projection, or migration. It must not own accounting, filing, billing,
authorization, direct persistence, provider operations, or cross-module
implementation imports.

## Public interface

Import only `talli_backend.modules.system_boundary.public`.

- Query contract: `SYSTEM_BOUNDARY_AVAILABLE`
- Stable error code: `BOUNDARY_UNAVAILABLE`
- Port protocol: `SystemBoundaryTransport`
- Adapter registration: `adapter_for`

The FastAPI adapter is selected by backend composition and registered in source
with `adapter_for(SystemBoundaryTransport)`, not selected by callers.

## Collaboration, ports, and tests

The module has no capability dependency, so it cannot introduce a cycle.
`SystemBoundaryTransport` is bound to `talli_backend.main.create_app` in
`architecture/backend-system.json`. Contract coverage is in
`apps/backend/tests/test_system_boundary.py`; manifest and import enforcement is
in `tests/architecture_foundation.test.mjs`.

## Compatibility and change rule

There are no compatibility exceptions. Change this document and `module.json`
together whenever its public interface, dependencies, port, ownership, or
forbidden responsibilities change.
