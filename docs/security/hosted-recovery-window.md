# Finite hosted recovery window

`talli-recovery-window` is a separate opt-in operational command, never composed
into FastAPI. Preparing configuration or passing local tests grants no hosted
authority. The November 3 window is consumed; its database commit/SQL containment
remain unknown and its target stays paused. Its time-limit failure is not erased
by this repair. No current configuration authorizes another hosted operation.

The importer records `diagnostics.json` under its existing private journal lock.
It retains at most 32 timestamped boundary events, same-process elapsed time and
one first-failure summary. Driver message patterns become fixed categories such
as `tls_connection_closed`; unrecognized messages remain unclassified. SQLSTATE
and a bounded typed cause chain distinguish known driver signals. Raw exception
text, SQL, row/object/actor values, DSNs, tokens, passwords and message hashes are
excluded. Pattern matches are hints, never proof of rollback or authority to retry.
Database connection, identity, data copy, checkpoint and commit have separate
boundaries. A killed process can leave a `started` boundary; that is not completion.

## Run contract

Use Python 3.12+ from the pinned environment. Call the module with
`python -B -m talli_backend.adapters.hosted_recovery_window` (or its installed
entry point). `start`, `supervise` and `cleanup` all require:

```text
--config /absolute/private/config.json
--expected-config-sha256 <reviewed digest>
--authority /absolute/private/approvals/new-authority.json
--expected-authority-sha256 <new owner-approved receipt digest>
```

`start` consumes a UUID-named `.used` receipt with exclusive creation, creates a
fresh work directory and launches the guardian in a new session. The acknowledgement
means only that the process launched. Require `guardian.json`/`window.started`
before treating an outage as admitted. The guardian itself performs fresh Free
organization and exact designation/engine/state checks, then records its absolute
cleanup deadline before the first pause request. A stable private authority
directory serializes guardians on that host. Do not distribute copied authority
directories to multiple runners; this is not a distributed lease or root sandbox.

The reviewed config version1 has exactly these fields:

- `work`, `credentials`: absolute owner-private paths. Credentials contain the
  existing `managementToken`; the guardian does not obtain new source credentials.
- `source`, `capacity`, `target`, `preserved`: distinct project designations
  (`project`, `organization`, `name`, `region`, exact `engine`) in one designated
  organization. Only capacity/target lifecycle operations are implemented.
- `workSeconds` <=2700, `callSeconds` <=15, `pollSeconds` <=5,
  `cleanupSeconds` <=900. They are finite positive numbers, not a service RTO.
- `worker`: reviewed `argv`, `cwd`, exact clean Git `head`/`tree`, and `files`
  mapping absolute paths to SHA256. Include the resolved executable, external
  procedure/capture/config pins and required source/tool dependencies. Arguments
  contain paths/digests, never secrets. The worker must not daemonize or escape its
  process group. Standard output/error are discarded; use the safe private journal.

The loader requires pins for its own resolved Python executable and the executing
guardian, diagnostics, target, capture and backup-recovery module files. A worker
Git head alone does not identify the code of an independently installed guardian.

The new authority version1 has exactly `windowId` (UUID), `configSha256`, an aware
`validBeforeUtc`, `maximumCharge:0`, `oneAttempt:true`, and this explicit
`availabilityAcknowledgement`:

```text
host-awake-only; no hard outage bound; external availability required for host-loss coverage
```

This schema binds a human decision; fabricating it is not approval. Old Nov3
receipts do not satisfy it. A used receipt or existing guardian journal cannot
start/resume a second attempt. Worker exit0 is not a product/recovery verdict.

Provider operations use fixed Supabase Management API GET metadata and POST
pause/restore endpoints, in bounded disposable processes with no redirects or
proxy environment. A lost response is unknown; GET reconciles it without repeating
the import. Every dispatched pause/resume stays in `pendingMutations` until its
requested goal is observed. The unchanged pre-request state never clears it:
a delayed pause can still take capacity offline after an initially healthy GET,
or a delayed resume can bring a currently paused target up later. Unresolved
mutations prevent cleanup success; no blind duplicate POST is issued. This
reconciliation assumes one lifecycle owner and the provider's metadata observations;
it is not a provider transaction receipt or a guarantee against later state changes.
Cleanup stops the worker process group, requests target pause, observes
INACTIVE, restores capacity, observes its original engine/ACTIVE_HEALTHY and checks
source/preserved state. It still attempts capacity restoration if target pause
cannot be verified. It never infers SQL containment. Provider failure yields an
unverified cleanup result, not success. Process-group stopping assumes reviewed
cooperative worker topology; it cannot revoke work that has escaped the host.

`cleanup` needs the exact consumed receipt and config, but may run after approval
expiry or loss/change of the worker checkout. It cannot start a worker or resume
the target. It does not kill a PID from a saved journal (PID reuse); previous
worker termination and SQL containment remain unverified. It writes a separate
numbered invocation journal from its first event and a separate cleanup receipt;
the original guardian acknowledgement/deadline/failure remain unchanged. Pending
mutations carry forward from the latest bound journal. Missing pending history
prevents a verified-cleanup claim. First safe failures per cleanup boundary survive
the event ring, alongside the original window deadline/failure. SIGTERM requests
cleanup of an active guardian; SIGKILL, host loss
or blocked local storage cannot be handled by that same process.

## What is actually enforced

An awake, scheduled guardian bounds child/provider-call waits without agent turns
or tool polling. UTC and same-process monotonic elapsed time both close work
admission; a clock discontinuity triggers cleanup. Stored monotonic origins are
never compared across processes. Python before3.10 on macOS uses a different
monotonic origin per process; the supported3.12 runtime was measured separately.

This is **conditional local enforcement**, not a hard wall-clock outage guarantee.
During host suspension/offline time or guardian loss, no local cleanup can run.
On resumption it can detect lateness, but cannot make an earlier deadline true.
UTC jumps, scheduling/storage stalls, lost network access and provider latency can
delay actions. Supabase can remain PAUSING/RESTORING after a timely request. No
local process, GitHub Actions queue or independent runner can guarantee the
provider's time to ACTIVE_HEALTHY. Budget polling/termination/IO margin before the
owner's cleanup-by time; do not schedule the worker cutoff at that exact bound.

Host-independent cleanup requires a separately available runner or managed timer,
armed and acknowledged **before** the first pause, with approved least-privilege
provider access, exact targets, immutable deadline and an independent cleanup-only
path. A runnable local guardian or an untested remote plan is not that evidence.
No always-on destination/access has been designated. Selecting/provisioning one,
credential transfer, alerting and any charge require their own concrete reviewed
proposal/authority. Until then, retain the paused unknown target and offline proof;
do not offer another laptop window as enforcing a strict limit through suspension.

Sources: [Python clock semantics](https://docs.python.org/3/library/time.html),
[Psycopg errors](https://www.psycopg.org/psycopg3/docs/api/errors.html),
[Supabase pause](https://supabase.com/docs/reference/api/v1-pause-a-project),
[restore](https://supabase.com/docs/reference/api/v1-restore-a-project),
[organization metadata](https://supabase.com/docs/reference/api/v1-get-an-organization).
