---
status: accepted
date: 2026-07-26
---

# Enforce Capability-Owned Contracts, Data, and Workflows

The Python backend will use the fifteen capabilities approved in issue #124.
Each capability owns one public package, its deterministic rules, same-named
Postgres schema and migrations, repositories, published events, and outbound
ports. Other capabilities use only immutable public command/query/event contracts.
They cannot import internals or access another capability's tables. Multi-capability
mutations run through named, thin application workflows inside one short Postgres
transaction; external I/O uses persisted idempotent state machines outside that
transaction. The shared kernel remains limited to the stable primitives explicitly
listed in issue #124.

The initial capability dependency graph must be acyclic before foundation exits.
In particular, filing workflows query `annual_compliance` for owned annual facts
and pass immutable snapshots into filing commands; filing capabilities do not
import `annual_compliance`. `annual_compliance` may aggregate the three filing
capabilities' published readiness/completion contracts. Event-triggered workflow
code may depend on several public packages, but those workflow edges are declared
in the backend system manifest and cannot hide a capability cycle.

## Database authorization seam

Business repositories use a restricted application database role that cannot
bypass RLS. After independently validating the Supabase token, the backend sets
the verified actor context transaction-locally. Capability-owned RLS policies call
small, versioned `company_access` database authorization functions; they do not
read `company_access` tables directly. Those functions derive identity from the
trusted transaction context, use a fixed search path and least privilege, and are
contract-tested for tenant concealment and connection-pool context leakage.
Service-role access is forbidden for ordinary business repositories and allowed
only for explicitly declared operational adapters.

## Technical state and ownership

Business module manifests do not cover technical runtime state. A separate,
schema-validated backend system manifest therefore owns and declares:

- named application workflows and all public packages they call;
- the operational control plane and its `launch_signoffs` data;
- transaction, idempotency, event-delivery, migration-runner, and durable-worker
  infrastructure that owns no business decisions;
- every technical schema/table and every binding from a capability-owned port to
  an adapter; and
- dependency direction from transport, workflows, adapters, and composition.

The operational control plane supplies deny-by-default release decisions through
declared ports and is rechecked at consequential provider adapters. It is not a
sixteenth business capability and cannot accumulate accounting, filing, billing,
or authorization policy.

## Canonical decision inputs

- Capability map and shared kernel: issue #124.
- Data and transaction ownership: issue #125.
- Public contracts and events: issue #126.
- Repository prototype: issue #130, commit `1c38dc6d`.

## Consequences

- Every business table has one capability owner; every technical table has one
  system-manifest owner.
- RLS remains genuine defense in depth after browser business persistence is
  removed.
- Audit inclusion, notification enqueue, and other multi-owner mutations are
  visible named workflows rather than hidden command chains.
- Adding a capability, technical subsystem, cross-capability dependency, or
  cross-module database reference requires manifest, documentation, architecture
  test, and ADR review.
