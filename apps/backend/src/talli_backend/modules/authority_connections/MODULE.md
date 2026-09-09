# Authority Connections backend capability

<!-- architecture-inventory
{"dependencies":[],"ownedTables":["authority_connections.authority_operations","authority_connections.system_user_requests"],"ports":["SystemUserAuthorityProvider","SystemUserPersistence","SystemUserStateTransaction","AuthorityOperationsPersistence","AuthorityOperationsProvider"],"publicEntryPoints":["talli_backend.modules.authority_connections.public"]}
-->

## Purpose and current slice

`authority_connections` owns System User request identity, connection state,
authority operations and verified connection/preflight evidence. The current
services migrate the existing owner RF-1086 request lifecycle and the two exact
admin operations for its System Register definition and callback. They create no
new right, obligation, company scope, registry operation or provider environment.
The owner lifecycle consumes the latest exact successful callback-operation audit
as its prerequisite.

Obligation-specific permission attestations and filing evidence remain with their
filing owners. RF payloads, approvals, journal/feedback rules and statutory
classification are outside this module. Backend-system owns `launch_signoffs`
and the authenticated web callback transport. This module owns no billing policy,
generic provider proxy or operational activation decision.

## Public contract

Consumers import only `talli_backend.modules.authority_connections.public`.
`AuthorityConnectionsCommands` exposes `start`, `retry` and `reconcile` over
immutable request commands. `AuthorityConnectionsQueries` exposes an owner-safe
result read, original-request owner resolution and the existing ordered owned
request projection. `SystemUserRequest`, `SystemUserIdentity`,
`SystemUserRequestObservation`, `QueriedSystemUser` and `SystemUserStateUpdate`
are immutable facts; identifiers, states and safe failure codes are validated.

The complete exported vocabulary is grouped by purpose:

- Owner commands and queries: `AuthorityConnectionsCommands`,
  `AuthorityConnectionsQueries`, `StartSystemUserRequestCommand`,
  `ReconcileSystemUserRequestCommand`, `SystemUserFlowResult`.
- Owner identity, state and observations: `SystemUserOwner`,
  `SystemUserIdentity`, `SystemUserRequest`, `SystemUserRequestStatus`,
  `SystemUserRequestObservation`, `QueriedSystemUser`, `SystemUserStateUpdate`,
  `SystemUserCallbackOperation`.
- Owner failures: `AuthorityConnectionsError`, `AuthorityConnectionsErrorCode`,
  `AuthorityProviderError`, `AuthorityFailureCode`.
- Fixed existing identity and URLs: `SYSTEM_USER_SYSTEM_ID`,
  `SYSTEM_USER_OBLIGATION`, `SYSTEM_USER_RIGHT`, `SYSTEM_USER_CALLBACK_URL`,
  `SYSTEM_USER_CALLBACK_PATH`, `SYSTEM_USER_CONFIRMATION_PREFIX`.
- Owner ports and binding markers: `SystemUserAuthorityProvider`,
  `SystemUserPersistence`, `SystemUserStateTransaction`,
  `system_user_authority_provider_adapter`, `system_user_persistence_adapter`.
- Admin commands, queries and immutable audit: `AuthorityOperationsCommands`,
  `AuthorityOperationsQueries`, `RunAuthorityOperationCommand`,
  `AuthorityOperationKind`, `AuthorityOperationIntent`,
  `AuthorityOperationCompletion`, `AuthorityOperationRecord`,
  `AuthorityOperationStatus`, `AuthorityOperationCode`, `AuthorityOperationError`.
- Admin ports and binding markers: `AuthorityOperationsPersistence`,
  `AuthorityOperationsProvider`, `authority_operations_persistence_adapter`,
  `authority_operations_provider_adapter`.

An owner-safe `SystemUserFlowResult` includes only the local request/company,
connection status, verified preflight time, validated confirmation URL and a
closed failure code. It never includes organization number, external reference,
provider request identity, token or credential. The internal immutable request
projection retains original identity, operator-evidence relationship and times
for existing authorized consumers. The transport must apply its own exact safe
response projection; a source projection is not a browser serialization policy.

`start` requires current owner authorization and fresh MFA. It verifies the
fixed callback audit before committing one `creating` intent and calling the
provider. A repeated insert cannot be treated as a new request. `retry` reads
the original stored identity; an ambiguous create performs a same-reference
lookup without another create. A later explicit retry can create only after an
independent authority HTTP 404 and another successful callback prerequisite.
Token failure or an unknown lookup never proves absence.

`reconcile` reads the original provider request or external reference. Accepted
state additionally requires the exact actual System User relationship and a
successful delegated RF grant before preflight is recorded. An existing verified
request still checks the actual System User, but retains the existing behavior
of not acquiring another delegated preflight grant. A recovered accepted request
from a creating-intent lookup has no implied preflight; normal reconciliation
must verify it. Terminal state cannot reopen.

Fresh MFA defaults to required for ordinary retry/reconcile. Only the separately
authenticated, cookie-derived callback composition may select
`require_fresh_mfa=False`; this is never a request-body authorization flag. The
callback resolves company/owner from the original UUID through the persistence
port and still independently authenticates the initiating owner. Read-only owner
projections preserve existing visibility without a new fresh-MFA requirement.

## Ports and transactions

`SystemUserPersistence` derives current `SystemUserOwner` facts from the verified
Company Access context. Every persistence operation rechecks the appropriate
current owner relationship inside a short request-bound transaction. Stores
enforce exact immutable identity, original provider reference, legal transitions,
one live request per company/obligation and terminal evidence integrity under
locks. `begin_request` commits once or fails; it must never return an old creating
intent as a newly inserted one. Original IDs, external/provider references and
evidence timestamps survive migration and retries. Time belongs to the durable
store; tests inject its fixed timestamps and a deterministic external-reference
generator.

`SystemUserStateTransaction` is the authority half of the named backend-system
state workflow. It locks the original request, applies the validated state and
checks current owner authorization before commit. The workflow preserves the
existing atomic accepted-to-verification-failed transition and suspension of
linked pilot authorization through Billing's narrow public transaction contract.
There is no direct billing table access, policy or uncoordinated after-commit
suspension in this module. The workflow's failure rolls back both existing
effects.

`SystemUserAuthorityProvider` exposes only `create_request`, `get_request`,
`find_request`, `query_system_user` and `verify_delegation`. The adapter uses the
fixed control write scope for create/query, read scope for get/find, and exact RF
delegation for preflight. It validates response shape/field counts, identifiers,
single right, callback/confirmation URL, timeouts and bounded errors. It acquires
and disposes of credentials/tokens internally and returns immutable observations
or `AuthorityProviderError` with a closed `AuthorityFailureCode`. A
`maskinporten_*` failure before create does not become an ambiguous create or a
negative connection assertion. No provider I/O runs inside a persistence
transaction.

`AuthorityOperationsPersistence` authorizes a current active admin and fresh MFA
before a write, inserts one redacted started audit, and completes that original
audit only while the initiating actor remains an active admin. Completion does
not impose a new MFA expiry check after provider I/O. A duplicate operation UUID
fails closed without executing the provider. Each explicit admin action has a
new server-generated UUID, as before; this is not a generic replay or lease API.
Listing returns at most the existing ten most recent audits to a current admin,
without requiring fresh MFA or restricting the audit list to its creator.

`AuthorityOperationsProvider.prepare` only checks disabled-by-default production
configuration and constructs the immutable fixed definition. Its canonical hash,
exact bytes and operation-specific redacted metadata are committed before
`execute` obtains a token. Only `register_rf1086_system` with exact confirmation
`REGISTER TALLI RF1086 SYSTEM` and `set_rf1086_systembruker_callback` with exact
confirmation `SET TALLI SYSTEMBRUKER CALLBACK` exist. Callers cannot supply
provider JSON, credentials, rights, client lists or callback URLs. Tokens use the
fixed System Register write scope and are disposed of inside the adapter.

Registration reads first, creates only on an independent 404, and reads back
after an acknowledged create. An uncertain create stays failed in its original
audit; a later explicit action reads the fixed system before considering another
create. Callback update never creates a missing system and replaces only the
exact existing empty-callback definition. It performs a readback even after a
failed or lost PUT; only the observed exact target confirms success. A changed
definition returns conflict. Provider errors are closed safe codes, and audit
completion failure prevents reporting success. Neither operation runs provider
I/O inside a persistence transaction.

The public binding markers are `system_user_persistence_adapter` and
`system_user_authority_provider_adapter`. Concrete adapters, transactions,
transport, runtime configuration and their bindings belong to backend-system
composition and the owner manifests. The service imports no framework, database
or provider library and no other capability internals.

## Verification and stage limits

`tests/test_authority_connections_service.py` characterizes owner authorization,
durable intent, exact callback evidence, ambiguous creation/recovery, provider
identity, delegated preflight, linked-state workflow invocation, terminal states,
safe projections and immutable typed state writes using deterministic boundary
fakes. `tests/test_authority_operations.py` verifies the two exact admin intents,
durable audit ordering, duplicate refusal, immutable completion and redacted
failures. `tests/test_altinn_authority_operations.py` uses local HTTP transports
to verify fixed production request bytes, read-before-write and uncertain
callback recovery, strict response bounds and token disposal. These tests do
not prove actual Altinn/Maskinporten behavior, database/RLS
isolation or hydrated browser/API integration. Those adapter and stage gates must
pass independently, including contracted consumers, rollback/recutover and the
two immutable complete customer-ready gates. These service slices are not #150 stage
exit, #151 filing migration, provider activation or final #192 acceptance.
