# Authority Connections web transport

This feature carries the authenticated existing System User owner journey through
the committed generated FastAPI client. The backend owns state, relationship,
scope, provider and MFA decisions. Web code retains forms, Norwegian presentation,
the HTTP-only local callback cookie and fixed-origin redirects.

The callback route alone signs a short-lived server transport proof over the
original cookie UUID and bearer digest. Its dedicated server key never enters a
browser bundle or provider credential contract. Both the proof and the original
owner's independently verified session are required at the backend callback.
Ordinary retry actions cannot select the callback's MFA exception.

All requests use no-store generated transport and bounded timeouts. Responses are
checked against the requested identity. No direct authority persistence, provider
HTTP, credential signing, connection state machine or filing logic belongs here.

<!-- architecture-inventory
{"publicEntryPoints":["@/features/authority-connections","apps/web/features/authority-connections","apps/web/features/authority-connections/index.ts"],"routes":["/auth/systembruker/confirm","/connections"],"apiOperations":["authorityConnectionsListSystemUserRequests","authorityConnectionsReconcileSystemUserCallback","authorityConnectionsReconcileSystemUserRequest","authorityConnectionsRetrySystemUserRequest","authorityConnectionsStartSystemUserRequest"]}
-->

<!-- architecture-inventory
{"apiOperations":["authorityConnectionsListOperations","authorityConnectionsRunOperation"]}
-->
