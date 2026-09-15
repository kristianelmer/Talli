# RF test-journal interruption safety — #193 partial work

Current bounded result: both final independent reviews PASS at source revision
`abb48eda31f75583629eb1ec9ecd71f676061317`; 83 focused tests pass.
See `journal-verification.json` and both reports under `reviews/`.
Provider authorization remains pending and no full RF criterion is accepted.

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

The b51c57d7 rereview found that partial archive pages could mint success on the
first invocation and fail validation on replay. One shared archive validator now
runs before both success checkpoints and accepted replay. Incomplete/unknown page
metadata produces `RF1086_ARCHIVE_INCOMPLETE`; confirmed intent remains available
for read-only recovery. The historical permissive pagination characterization is
explicitly tightened. Full multi-page archive acquisition remains required RF
completion work, not a permanent supported-scope exclusion.

After these corrections, all 83 focused tests pass (18.64 seconds), including a
partial archive followed by GET-only recovery. The original review failures remain
preserved. Final independent rereview is pending; no complete RF gate is claimed.

## Authorized test baseline — 15 September 2026

The owner approved the prepared request. The existing test credential obtained
HTTP200, followed by HTTP200 for each of the three exact approved filing POSTs.
The durable confirmation is retained. Five approved archive GETs returned HTTP404;
the final retained error is GLD_021. No filing POST was repeated and no mutation
remains pending. The run stopped at its approved request bound.

`provider-baseline-20260915.json` records SUBMISSION_CONFIRMED_ARCHIVE_PENDING.
An independent review passed50 consistency checks. Archive verification and final
business acceptance remain unproved. Further read-only recovery is prepared but
requires an extension of the exhausted five-read authorization; no new filing,
production action, credential activation or paid step is authorized by that plan.
