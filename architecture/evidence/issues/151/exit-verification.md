# RF stage exit verification

Implementation candidate: `dd1a7dba8192746f5e882d5b119d895bf7730ce1`.
Predecessor: `91b178c281bcc5fb887a6257d2f72e380199f3e6`.
This record supplements the historical focused evidence; it does not yet claim
the second complete gate, protected integration or closure of #151/#192.

The first immutable customer-ready gate passed all eleven checks between
2026-09-10T12:46:33.872Z and 2026-09-10T13:06:15.791Z. Its exact
[receipt](../../customer-ready-gates/dd1a7dba8192746f5e882d5b119d895bf7730ce1.json)
and [transcript](../../customer-ready-gates/dd1a7dba8192746f5e882d5b119d895bf7730ce1.log)
include the final 130-case RF/authority database suite, 699 Billing database
cases, 11 historical browser checks and 12 fresh RF browser checks, all passing
without skips in those lanes. The 12 fresh checks comprise one complete hydrated
journey and eleven fixture guards. Counts across suites are not unique totals.

The backend boundary has two pre-existing optional environment-gated skips.
The validation-observation Python lane has one pre-existing optional skip because
`TALLI_VALIDATION_OBSERVATION_TEST_DATABASE_URL` is absent; its mandatory Node
database rehearsal passed. Supabase advisors report zero blocking security/error
findings and 60 performance warnings. Production dependency audits pass. The final
clean-tree check passed before the producer wrote its receipt and transcript.

The [bounded Spec acceptance](approved-amendment/candidate-spec-acceptance.md)
and [exit-envelope mapping](approved-amendment/exit-envelope-mapping.md) distinguish
implementation review from full release acceptance. The mapping found one extra
protocol-evidence gap that the generic system-boundary deployment smoke did not
cover. The subsequent [RF protocol proof](exit-protocol/README.md) closes that
bounded gap: 29 checks across 33 actual loopback API requests passed against exact
predecessor/candidate application, generated-client and transport sources. Root
independently repeated the unchanged harness under the gate's Node 24.20.0 runtime;
the [repeat transcript](exit-protocol/node24-repeat/transcript.log) also passes.
Source and artifact hashes are retained with both runs. The
[independent Spec closure](exit-protocol/independent-spec-closure.md) verifies
both runs and their exact source bindings. These use existing local
in-memory session/persistence/provider ports and six extracted action bodies;
they are not additional database or hydrated-browser evidence.

## Deployment and rollback sequence

For a separately authorized hosted rollout, deploy the expanded schema and backend
before switching clients to the new preparation API. Quiesce obsolete direct RF
preparation writes before changing the single writer. Switch the complete RF web
slice to the generated API, verify canonical behavior, retain the rollback window,
then apply the final contract. Contract is last; old preparation UI is not promised
to remain writable after writer cutover.

The protocol proof exercises retained Send and recovery in both version orders.
A new preparation client reaching the predecessor's missing routes receives an
unavailable error and performs no sibling fallback, public write, audit mutation
or success redirect. A missing route is not the typed RF record-not-found response.
Repeated and unknown submissions preserve operation identity without a blind POST.
The separate database gate proves overlap shares one durable journal and both
rollback forms preserve original identities, quarantine and archive generations.

Rollback must restore the matching application/schema phase and its prior single
writer through the shipped reverse artifacts. Reconcile unknown external effects
from the permanent journal; do not resend them merely because an application was
rolled back. The lifecycle rehearsal verifies reverse and recutover, exact sibling
preservation, malformed-quarantine rejection and atomic failure.

This work has not applied hosted migrations, enabled a provider, made a live filing
or promoted production. The frozen production revision remains
`d331ee2717d1eeacef0d81db42b9d4fb5848b408`. A seven-day activated-production
observation is not claimed. The successor remains blocked on protected #151 exit.
