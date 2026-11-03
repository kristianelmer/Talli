# Independent cleanup protocol preparation

This is operational code and an **inactive** workflow template, outside FastAPI.
It does not deploy, arm a runner, grant access or authorize a hosted operation.
November 3's hosted window remains consumed, over time and unknown at the database
boundary. Do not reuse its approval or execution packet.

The preparation adds a remote cleanup owner and a local coordinator. Independent
process tests stop/kill the local coordinator while a loopback provider and the
remote process continue. These are process scheduling tests on one machine, not
hardware suspend, GitHub availability or a provider restoration-time guarantee.

## Authority and acknowledgement

Public configuration binds the exact projects, coordinator public key, window
UUID, source commit, mailbox issue, mode and absolute UTC cleanup cutoff. A new
human authority binds its exact bytes and expiry, one attempt, $0 maximum, mode
and availability qualification. The old guardian authority has a different
schema and cannot substitute for it. Never fabricate an authority file and call
it owner approval.

Every signed envelope additionally binds repository, workflow path, numeric
GitHub run ID, attempt1 and numeric job ID. The remote runner generates a private
Ed25519 key in its private job directory. It publishes only the public key,
signed arm receipt and runtime identity. Bootstrap that public key by checking
actual GitHub run/job metadata and the arm artifact's API digest and exact member
bytes. A self-signature, bot author, artifact name or claimed job ID alone is
insufficient. Trust still includes GitHub and the exact approved workflow source.

`coordinate` requires the downloaded arm ZIP, its exact artifact ID, expected
run/job IDs, configuration/authority hashes and local private key. A queued or
dispatched run is not armed. Admission needs the actual in-progress job and a
fresh matching signed arm receipt before `armBeforeUtc`. It consumes a durable
one-use coordinator receipt even if subsequent admission fails. Keep one private
coordinator authority directory; do not copy it or the private key to multiple
hosts. This is not a distributed lease or root sandbox.

Before either permitted local lifecycle request (pause capacity; then restore
target), the coordinator publishes a signed sequenced intent. The remote records
it durably **before** publishing a signed acknowledgement. The coordinator checks
that exact command, fresh acknowledgement and current job, then exclusively
persists consumption **before** dispatch. Neither side treats a missing/lost
response as rejection. No duplicate lifecycle request or importer retry follows
from a timeout. An unchanged pre-request state cannot clear an intent; the remote
must freshly observe its requested goal. Source and preserved projects cannot be
mutated by this protocol.

Arming alone does not establish lifecycle cleanup ownership. A runner with no
accepted local lifecycle intent never issues cleanup POSTs, even if another owner
has changed the observed project states. An accepted intent with a lost ACK still
retains conservative cleanup ownership and its pending obligation.

The remote is the only cleanup owner. The local coordinator stops/reaps its held
worker on cancellation, exhausted deadline or failed heartbeat. It cannot prove
worker termination after its own loss. At the shared cutoff or early close the
remote pauses target and restores capacity on the original engine, using the
existing conservative lifecycle reconciler. It retains unresolved intents and
first safe cleanup failures. It never infers SQL rollback or containment.

SIGTERM requests best-effort remote cleanup. SIGKILL, runner/service loss, blocked
storage/network or hard GitHub cancellation can interrupt it. A stopped remote
process cannot act until resumed and reports the missed cutoff. Provider state
transitions can finish after requests/time budgets. No hard outage RTO is offered.

## Recovery and mailbox limits

GitHub issue comments are authenticated transport with signed application
messages. They can be edited/deleted; signatures cannot prove an undeleted tail.
Full bounded scans follow validated pagination, detect changed observed comments,
and use ETags. Auth/rate-limit/bound failures stop admission, rather than spinning
or replaying POSTs. GitHub's repository token budget is shared; conditional reads
do not guarantee service availability or unlimited secondary limits.

`recover` is observe-only when complete history is unavailable: no worker or
provider lifecycle POST.
It verifies the pinned original arm artifact, authenticates retained state and
later intents, and writes a new journal. An optional prior journal requires its independently
pinned SHA and exact binding; its bytes remain unchanged. Mailbox reconstruction alone always sets
`pendingHistoryKnown=false`; even healthy final metadata cannot turn that into a
verified complete-history cleanup result or permission to redispatch cleanup.
A lost remote owner therefore needs explicit inspection and a separately bound
mutating recovery decision; visible state alone is insufficient. Original/previous journals remain
unchanged. A lost or expired arm artifact, missing trusted binding, unavailable
GitHub history or absent provider credential is an explicit recovery dependency,
not permission to invent an empty history or trust another public key.

## Runnable interfaces

Use the pinned supported Python3.12 environment; all commands are opt-in:

```text
python -B -m talli_backend.adapters.hosted_recovery_remote serve|coordinate|recover
  --config /private/config.json --expected-config-sha256 <digest>
  --authority /private/new-authority.json --expected-authority-sha256 <digest>
  --credentials /private/credentials.json --work /private/new-session
```

`serve` requires actual GitHub run/workflow environment identity. It resolves and
checks the actual numeric job ID, checks the clean approved Git source and
executing module bytes, then starts the separate owner. A future cleanup-mode
config must pin the remote Python executable bytes; the metadata-only pilot can
record previously unknown Linux Python bytes without admitting lifecycle work.

`coordinate` additionally takes `--run-id`, `--job-id`, `--artifact-id`,
`--arm-archive`, and `--coordinator-key`. Cleanup mode additionally needs a
`--worker-config` with reviewed argv/cwd/head/tree and all executing source/tool
pins. The worker is stopped before cleanup cutoff with transport/kill margin.
A finish acknowledgement requests cleanup; it is not cleanup acceptance. Read
and independently verify the remote result artifact separately.

`recover` requires the original run/job/artifact and arm archive too, but accepts
expired authority solely for observation/reconciliation. It accepts optional
`--prior-journal` plus `--expected-prior-journal-sha256` to preserve known pending
cleanup intents. It performs no lifecycle POST with unknown history. A changed/expired artifact or unavailable
metadata refuses; it does not bootstrap from untrusted mailbox keys. It writes a
new private directory and returns nonzero when history is unverified.

The inert [workflow template](workflows/talli-recovery-cleanup.yml) supports only
metadata mode, a maximum five-minute cutoff and no lifecycle credentials. It
checks inputs as data, owns/reaps its runtime child, publishes the arm while the
job still runs, and uploads only public arm/result files. Its Linux wrapper
checks process start identity before best-effort cancellation. Job/service loss
can still prevent stop and cleanup; `always()` is not an availability guarantee.

## Smallest proposed hosted pilot

No pilot or access grant is approved here. Proposed later review scope:

1. Register the [credential-free default-branch stub](workflows/talli-recovery-cleanup-registration.yml)
   at the exact workflow path, without merging the stacked product PRs. Then
   copy only the reviewed runtime template to that path on a separate reviewed
   activation ref, retaining its exact source SHA and passing CI. Neither
   template is active here. Use a preconfigured `talli-recovery-cleanup-pilot` environment.
   Verify available reviewers, prevent-self-review, bypass and selected-ref rules;
   an environment name alone is not protection. Do not merge PR237 implicitly or
   change repository visibility/plan. A single-owner review gate may allow
   self-review explicitly; it is not two-person authorization. Public Free
   supports these environment controls. The current Talli repository is public;
   its new workflow path is absent from `main`. At the preparation readback,
   web Production tracked `release/production`, with no deploy hooks, and the
   backend had no Git link. Recheck before registration; do not change Production
   branch, hooks, domains or runtime settings.
2. Use one designated mailbox issue. Remote job permissions: Contents read,
   Actions read, Issues write. Local selected-repository integration: Actions read
   and Issues write; dispatch additionally needs Actions write if automated.
   No secret enumeration, Actions write in the remote job or provider billing/API
   key/database privileges are needed.
3. Grant a new short-lived Supabase scoped PAT with only **Project Settings Read
   (`project_admin_read`) for source `pkpyyxryfhfehrbhbynp`**. This pilot performs
   one exact source-project metadata GET, no organization/list/SQL/key lookup and
   no lifecycle call. OAuth's equivalent namespace is `projects:read`; do not
   infer selected-project scope from that name. Other declared project bindings
   are not freshly verified by this narrow pilot.
4. Store only that token in the explicitly approved environment secret
   `TALLI_RECOVERY_METADATA_TOKEN`. The local signing private key remains local;
   the remote ephemeral private key remains in its job. Artifacts/comments carry
   no private key, provider token, backup/capture bytes, company data or actor
   password/TOTP. Remove temporary credential/key files after the run; do not
   claim forensic erasure.
5. Run one metadata-only signed arm/heartbeat/close session, at most five minutes,
   $0 cap. Verify actual source metadata, source/workflow/run/job binding, artifact
   digest, fresh nonce acknowledgement and no lifecycle admission. Cancel/close
   without affecting any project, then inspect and seal receipts.

Project Settings Read-write (`project_admin_write`) also enables operations such
as project deletion; it is not a pause/restore-only grant. No such grant or new
outage is proposed by this metadata pilot. Keep source/elmerai service and the
unknown paused recovery targets as last verified; this file makes no fresh health
assertion. A failed pilot remains evidence, not authority to retry or escalate. Automatic
restoration after loss of the remote owner remains unavailable without a trusted
complete history and a separately reviewed mutating recovery scope.

Official references: [Supabase PAT scope controls](https://supabase.com/docs/guides/platform/personal-access-tokens),
[metadata permissions](https://supabase.com/docs/reference/api/v1-get-project),
[write/delete scope](https://supabase.com/docs/reference/api/v1-delete-a-project),
[GitHub comments](https://docs.github.com/en/rest/issues/comments),
[artifact provenance](https://docs.github.com/en/rest/actions/artifacts),
[environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[cancellation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation),
[rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
