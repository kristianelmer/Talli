# <Module name>

## Purpose

One paragraph describing the behavior hidden behind this module's public
interface and the value it provides to callers.

## Owns

- Domain or presentation responsibilities that belong here.
- Data, routes, operations, ports, or artifacts owned here.

## Must not own

- Neighboring responsibilities that are tempting but forbidden.
- Framework, persistence, provider, or business-policy details that must not
  cross this module's seam.

## Public interface

State the one supported import path and list its explicit exports. Document
invariants, coded errors, ordering, configuration, and other facts a caller must
know. Do not expose internal entities or file paths as contract.

## Data or route ownership

For a backend capability, list owned schemas, tables, buckets, projections, and
migrations. For a web feature, list owned routes and generated OpenAPI operation
IDs. Write `None` when a category is deliberately empty.

## Collaboration

List each declared dependency, its kind (`query`, `event`, or `feature`), and a
short example. State why the dependency direction remains acyclic.

## Ports and adapters

Backend only: list capability-owned ports and every approved concrete binding.
Explain any fail-closed or idempotency behavior callers need to know.

## Cache and browser policy

Web only: state the default cache policy, narrowly allowed caching, and every
approved direct-browser flow. Write `None` when there is no exception.

## Errors and events

List stable public error codes and published event schemas. Explain semantics,
not implementation exceptions or provider payloads.

## Tests

Point to colocated unit/feature and public-contract tests, plus any named
cross-module, provider-port, HTTP-contract, architecture, or release seam.

## Compatibility

List registry IDs for active exceptions. Each must have an owner, creation and
removal issue, exact paths, expiry, and removal condition. Write `None` when
there is no exception.

## Change rule

This document and `module.json` must change in the same contribution whenever
ownership, the public interface, dependencies, ports, data/routes, cache/browser
policy, or forbidden responsibilities change.
