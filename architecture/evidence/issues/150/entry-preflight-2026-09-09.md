# #150 entry preflight

Task `01a08515-2cd8-7093-8a34-3b9b3d458840` resumes the full #192 destination
through the approved serialized source route. This is entry evidence, not a
capability exit, source-provider conformance, hosted acceptance or final #192
completion receipt.

The live #150 ticket, #132 stage envelope, CONTEXT.md, ADRs 0010–0013 and
[integrated execution control plane](../../../../docs/architecture/mass-market-execution-control-plane.md)
were inspected. The destination and remaining source sequence are bound by the
[final source handoff map](../192/final-source-handoff-map-2026-09-09.md).
#137 is closed; the #192 interim receipt confirms protected and exact-main
integration at `b30312de11ad942479421def243e4a2252fbf166`. #192 remains open and
its billing implementation pauses during the source stages.

At the live claim preflight, #150 was open, unassigned and had no implementation
claim; its only two comments record this task's exact relocation proposal and
owner approval. Main still resolved to the integrated revision above, with no
open pull requests. The clean canonical entry run completed at
`2026-09-09T11:57:03.625Z`: all eleven checks passed. Its immutable
[receipt](../../customer-ready-gates/b30312de11ad942479421def243e4a2252fbf166.json)
and transcript are stored unchanged. Receipt schema, eleven distinct passing
checks, transcript markers and SHA-256, and tested-revision producer digest were
independently verified. This entry run is not one of #150's two final gates.

## Scope and preserved consumers

Authority Connections owns the existing RF System User lifecycle, delegation,
global registration/callback operations and their redacted audit. It does not
own RF statutory payloads, filing journals, billing entitlement policy or
Documents storage. The accepted later semantic disposition assigns only
connection/preflight row families to #150: obligation-specific
`authority_permissions` and filing evidence remain with their filing owners.
`launch_signoffs` remains backend-system technical state.

The two frozen RF credential consumers require the exact additional amendment
now [approved by Kristian](https://github.com/kristianelmer/Talli/issues/150#issuecomment-5601323119).
The [binding scope](rf-credential-relocation-2026-09-09.md) lists every affected
future tuple, helper, SQL routine, HTTP method and preserved effect. It grants no
generic future-capability migration or provider activation authority.

The first implementation slice is the durable owner System User
start/read/retry/reconcile and callback/preflight flow. Persistence cutover must
preserve the published RF, Billing and case-bound Company Access projections.
The existing accepted-to-verification-failed transition atomically suspends a
linked active pilot entitlement; preserve it through named owned contracts, not
a second billing writer. Founder operations and backend-system signoffs follow,
then the exact RF relocation and all remaining TypeScript credential paths.

Characterization identified unregistered deep flow, static schema and browser
suites. Current contracted RLS, migration/rollback/recutover and real hydrated
owner journeys must be registered in mandatory lanes, alongside fail-closed
provider and authorization tests. Static historical migration assertions are
not evidence of current RLS. Standard tests use local fakes; imported provider
evidence is never represented as a newly executed conformance run.

## Execution and completion

One root integration owner coordinates bounded non-overlapping contributions
inside #150. Every criterion is tracked in [requirements.json](requirements.json).
No downstream source stage begins before #150's full stage envelope, independent
review, two linked immutable complete gates, protected integration and exact-main
verification. No production pointer, purchase, real filing or named-company
operation is authorized by this claim. The existing control plane defines those
action-time gates; ordinary preauthorized repository operations continue.
