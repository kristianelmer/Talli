# RF test-journal interruption safety — #193 partial work

RF is the only active #193 obligation. #153 closed with reviewed merged evidence;
Tax, Accounts production completion, Annual #149, #208 and final #192 remain waiting.
This change addresses the local RF authority-test command, not the production SQL journal.
It does not complete any whole #193 acceptance criterion.

A mock-transport regression reproduced automatic POST replay after a response timeout.
The original private failure remains preserved. New tests cover all three mutation
stages and require a reconciliation error before credentials, network or journal rewrite.

The command holds a persistent canonical-path sidecar lock across all await points.
It flushes and synchronizes each checkpoint before a POST, binding the pending operation
to its existing UUID and exact body hash. A successful response clears that marker only
in the durable response checkpoint. A timeout, process death, malformed response or
failed response checkpoint retains uncertain intent and blocks automatic replay.
Legacy unconfirmed journals cannot prove the absence of a write and need reconciliation.
Confirmed legacy journals may recover through GET; accepted replay remains offline.
Malformed or missing keys cannot create new intent.

Two characterization expectations intentionally tighten: HTTP 503 from a POST no longer
permits a repeated write, and invalid saved keys fail before token acquisition. Statutory
XML, request order, environment/scope/company guards, GET polling and saved UUIDs remain
covered by the original tests. Schema version 2 identifies durable pending markers;
version 1 confirmed/accepted history remains readable after integrity checks.

Focused validation: 68 tests pass in the RF command and journal test modules, including
real child-process termination and concurrent alias locking using mock HTTP only.
Architecture check and diff whitespace check pass. Independent reviews are pending.
These focused checks are not either of the two complete RF exit gates.

Remaining RF work includes current official code meanings and capital-event coverage,
complete correction and final business-feedback handling, current service conformance,
representative genuine-company production evidence, and all seven original criteria.
The historical CLI status `accepted` reports archived transport documents, not final
business acceptance. No current provider call, credential activation, hosted mutation,
production promotion or genuine filing has been performed by this change.

## Independent review corrections

The first Spec review reproduced three file/evidence defects. Preparation now uses
a fresh temporary directory, so only the current generated child extent can be sent.
Retained payloads live under `.<evidence-filename>.xml` beside their journal and are
published only after prior payload and intent checks; a rejected invocation cannot
overwrite earlier XML. The former shared `xml/` folder is no longer used or modified.
Accepted replay validates nonempty document hashes/count, archive reference and GET
call against the recorded confirmation before reporting the saved transport success.
These changes preserve the original review failures and add direct regression tests.
