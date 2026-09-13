# Tax settlement slice acceptance

Company Tax owns settlement capture, validation and persistence. Ledger retains
posting policy, Banking retains matching, and Documents retains evidence storage
and removal checks. The released capture API, accounting outcomes, thirteen
source fields, receipt identity and after-commit Audit continuation are preserved.
Annual tax estimation and company-tax filing remain the next slice, #152.

The current linked complete customer-ready gates pass on
`50f969c04f4eabbe17ee2fcee36ac652d5ddcc05` and
`fd78d3bbcf563dbc991f84c703b6816e088bca26`. The latter explicitly links the former.
Their only non-evidence source difference strengthens the RF browser's
synchronization: it waits for the matching save response to finish before reading
persisted review comments. All existing persistence and later journey assertions
remain intact. Application and SQL bytes are unchanged between these gates.
The [updated independent pair review](updated-gate-pair/updated-gate-pair-independent-review-fd78d3bb.md)
checks both actual receipts, all eleven sections, schema, producer/transcript and
canonical hashes, chronology, exact link, Git ancestry and the source delta.
The historical `aad6bb90` gate and previous pair review remain available.

Both current gates include 22 Tax lifecycle/API tests, three restricted
runtime/concurrency tests and every required browser lane. Two pre-existing
optional backend skips, one optional validation-observation Python skip and 60
nonblocking advisor performance warnings are disclosed. Required Tax database and
browser lanes have no skips. Separate CI passes Application, Database isolation
and Release gate on `fd78d3bb`; final integration-head and exact-main verification
remain required.

The [exit-envelope review](final-acceptance/final-spec-exit-envelope-aad6bb90-closure.md)
checks the six original issue criteria and common migration requirements.
The refreshed pinned-predecessor proof executes original receipt replay, fresh
linked payment, replay and document retention after rollback from current SQL.
It first removes ambient Tax-helper access, proves the current cutover installs
the precise execution grant, and checks retention without borrowed owner roles.
Canonical cutover and final contract are restored afterward. These are synthetic
local tests through the real restricted adapter/API with fixture authentication.

CI originally exposed a premature RF saved-comment assertion at `50f969c0`.
An unchanged retry passed, but the failure recurred at `42ebfe85`. The later
[red/green reproduction](browser-sync-followup/manifest.json) proves the timing
window on the actual local browser workflow: with CPU throttling, the immediate
query returned zero comments and a later diagnostic read returned one without
another click. The same instrumentation and throttle pass the complete journey
with the response-completion wait. This identifies a reproducible synchronization
fault; it does not claim identical scheduling in CI. Prior failed attempts retain
zero exit credit. Independent Spec and Standards reviews preserve the original
assertions and verify source/evidence hashes and isolated failure behavior.

For a separately authorized hosted rollout, expand the schema and deploy the new
backend before switching the web client. Quiesce the previous writer at cutover,
reconcile counts and hashes, and retain the rollback window before final contract.
The new preview client fails safely against the old backend. The predecessor backend’s capture implementation fails unavailable against the
contracted schema; rollback requires the matching old application and physical
source. The released v1 capture endpoint remains supported by the new backend. Both rollback forms preserve facts and prevent
dual writers. No hosted migration, provider activation, genuine filing, production
promotion or activated-production observation is claimed. Production remains
frozen at `d331ee2717d1eeacef0d81db42b9d4fb5848b408`.
