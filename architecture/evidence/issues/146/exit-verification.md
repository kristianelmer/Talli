# Tax settlement slice acceptance

Company Tax owns settlement capture, validation and persistence. Ledger retains
posting policy, Banking retains matching, and Documents retains evidence storage
and removal checks. The released capture API, accounting outcomes, thirteen
source fields, receipt identity and after-commit Audit continuation are preserved.
Annual tax estimation and company-tax filing remain the next slice, #152.

The complete customer-ready gates passed on `aad6bb90951120b09771a23f58d5b662713e7a5a`
and `50f969c04f4eabbe17ee2fcee36ac652d5ddcc05`, with an explicit predecessor link.
Only evidence changed between them. Both passed all eleven sections, including
22 Tax lifecycle/API tests, three restricted runtime/concurrency tests and every
required browser lane. The [independent pair review](gate-pair/gate-pair-independent-review-146.md)
records schema, producer/transcript/canonical hashes, chronology and ancestry.
Two pre-existing optional backend skips, one optional validation-observation
Python skip and 60 nonblocking advisor performance warnings are disclosed there.
Required Tax database and browser lanes have no skips.

The [exit-envelope review](final-acceptance/final-spec-exit-envelope-aad6bb90-closure.md)
checks the six original issue criteria and common migration requirements.
The refreshed pinned-predecessor proof executes original receipt replay, fresh
linked payment, replay and document retention after rollback from current SQL.
It first removes ambient Tax-helper access, proves the current cutover installs
the precise execution grant, and checks retention without borrowed owner roles.
Canonical cutover and final contract are restored afterward. These are synthetic
local tests through the real restricted adapter/API with fixture authentication.

CI passed the application and database Release gate on `aad6bb90`. CI's first
`50f969c0` attempt failed the RF browser's immediate saved-comment assertion;
all 25 Tax database tests passed, but the later Tax browser lane was not reached.
The [failure record](gate-pair/ci-failure-attempt1-50f969c0.json) and independent
assessment retain that failed attempt without assigning an unproven cause.
The unchanged CI retry passed every required job, including the RF and subsequent
Tax/public browser journeys; its result remains separate from both local passing
receipts. Both receipts were stored in `ddcdd34e` and independently reread from
committed bytes. No synchronization cause or product fix is inferred from the retry.
Protected integration requires a passing exact-head Release/Preview and subsequent
exact-main verification. Local acceptance alone does not close #146.

For a separately authorized hosted rollout, expand the schema and deploy the new
backend before switching the web client. Quiesce the previous writer at cutover,
reconcile counts and hashes, and retain the rollback window before final contract.
The new preview client fails safely against the old backend. The old capture API
fails unavailable after final contract; rollback requires the matching old
application and physical source. Both rollback forms preserve facts and prevent
dual writers. No hosted migration, provider activation, genuine filing, production
promotion or activated-production observation is claimed. Production remains
frozen at `d331ee2717d1eeacef0d81db42b9d4fb5848b408`.
