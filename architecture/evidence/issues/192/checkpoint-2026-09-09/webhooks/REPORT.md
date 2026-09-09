# Issue 192: actual Vipps MT webhook evidence

Status: actual MT refund notification received and authenticated, exact-byte duplicate replay and tamper rejection passed. All temporary callback resources have been cleaned up. This report proves notification transport/storage; authoritative payment outcomes are established separately by provider GET reconciliation.

## Scope

MSN 535717, Vipps merchant test only (`https://apitest.vipps.no`). Callback registration `58e21a30-68d3-455d-886c-a9427d2cecea` is unique to this run and subscribes to the 10 recurring event types accepted by the shipped adapter. No agreement, charge, refund, or stop mutations were performed by this webhook verifier. Parent operator controls those operations and their separate evidence.

The exact shipped `create_app` annual notification route is composed using `compose_annual_billing_runtime`. A temporary ASGI wrapper exposes only the notification POST and a health GET; it records exact request bytes and headers privately, without altering the submitted body. Other business routes return 404. A real local PostgreSQL database `talli_192_webhook_ea3801ae` has only the shipped `20260906204352_annual_notification_receipts.sql` migration. Its unique runtime LOGIN has only non-inherited SET membership in `annual_notification_executor`, no bypass-RLS/admin role attributes, and no business schema. The shared full-test database is untouched.

## Sources and cost

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) explicitly documents a free tunnel for testing. [Cloudflare tunnel setup](https://developers.cloudflare.com/sandbox/api/tunnels/) documents no account/API token/domain requirement for a Quick Tunnel. Downloaded official cloudflared 2026.8.3 to the private temporary directory; no installation, signup, paid activation, persistent Cloudflare tunnel, or domain registration.
- [Vipps webhook registration](https://developer.vippsmobilepay.com/docs/APIs/webhooks-api/api-guide/) documents MT registration, event subscriptions and deletion.
- [Vipps HMAC authentication](https://developer.vippsmobilepay.com/docs/APIs/webhooks-api/request-authentication/) specifies SHA256 of exact body and the method/path/date/host/contenthash canonical string. The shipped verifier uses the secret as UTF-8 bytes, as documented.

## Readiness checks

`readiness.json` records public HTTPS health 200, unsigned callback 401, inaccessible checkout route 404, and SHA256 of shipped sources used. `database-authority.json` records the restricted role properties and empty receipt baseline. The runtime configuration and provider registration secret are stored in mode0600 private files inside the original mode0700 private archive, not in this sanitized directory. Secrets, tokens and signature headers must never be copied into repository evidence.

## Actual refund notification

At 2026-09-09T08:22:33.927228Z, the callback received actual `recurring.charge-refunded.v1` for `agr_Un4JzLG` and original charge `talli-mt-9c98eaff-c260-51f2-98a6-542816c898aa`. The shipped HMAC intake returned 200 and committed receipt `24e62020-0bf9-4eaa-a921-efe5855c7b60`. Exact body SHA256: `9fe1f22645ac4ce12baa98562b5c1dbe4effbda753737c2e28377f7e54ff10b7`; 402 bytes. Three local replays through public HTTPS used the original exact bytes and signed headers, returned 200, and preserved the same single receipt including ID and receipt time. Appending one byte while preserving the original signature returned 401; no additional receipt was inserted. See the public `webhook-evidence.json` replay checks; the detailed per-delivery verification remains in the private archive.

## Complete event inventory

Eight unique genuine MT deliveries passed HMAC authentication and committed eight technical receipts. Nine locally initiated exact-byte replays across the first refund, independent full refund, and STOP event returned 200 without changing receipts. Three locally modified-body probes returned 401, as did the unsigned readiness probe.

| Event | Agreement | First delivery UTC | Receipt ID |
|---|---|---|---|
| `recurring.charge-refunded.v1` | `agr_Un4JzLG` | 2026-09-09T08:22:33.927228+00:00 | `24e62020-0bf9-4eaa-a921-efe5855c7b60` |
| `recurring.agreement-expired.v1` | `agr_5YSKYz2` | 2026-09-09T08:22:57.051642+00:00 | `47b166c8-bb5e-41d6-ae21-5e53b91c2412` |
| `recurring.charge-refunded.v1` | `agr_Un4JzLG` | 2026-09-09T08:23:36.564921+00:00 | `ae38af96-1c2a-4527-946c-2a5905a89dee` |
| `recurring.charge-canceled.v1` | `agr_Un4JzLG` | 2026-09-09T08:23:45.301665+00:00 | `9efd12a9-972b-437f-b728-feba2ca9d402` |
| `recurring.charge-captured.v1` | `agr_Xwpy7fP` | 2026-09-09T08:24:31.091198+00:00 | `f6132dd8-354c-4db2-8749-a19220a5c86c` |
| `recurring.agreement-activated.v1` | `agr_Xwpy7fP` | 2026-09-09T08:24:31.927377+00:00 | `6ee08697-bb50-413f-b060-4d95f601c31d` |
| `recurring.charge-refunded.v1` | `agr_Xwpy7fP` | 2026-09-09T08:24:41.769651+00:00 | `380bc0f3-de7c-43a7-a067-1c4f876ce802` |
| `recurring.agreement-stopped.v1` | `agr_Xwpy7fP` | 2026-09-09T08:24:44.392557+00:00 | `2bf9f4fb-de24-43b1-aab4-054c21a36686` |

The second agreement `agr_Xwpy7fP` delivered capture, activation, full refund, and merchant STOP events. The accidental unapproved duplicate `agr_5YSKYz2` delivered an expiry event, labeled only as expiry/cleanup evidence. Actual GET-confirmed payment outcomes remain in the parent MT verification.

## Evidence artifacts

Published here: `webhook-evidence.json` contains the actual events, replay/tamper checks and source hashes; `readiness.json` records HTTPS readiness and source hashes; `database-authority.json` records the restricted runtime role; `receipts-final.json` exports the technical receipts; `cleanup.json` verifies removal of the temporary resources.

Registration responses, detailed verification files, delivery logs, replay harnesses and private captures/configuration remain in the local private archive. Raw bodies with original signed headers, tokens and secrets are intentionally excluded from this sanitized copy.

## Attribution limits

An authenticated webhook is a technical delivery receipt, not a financial settlement or entitlement decision. This verifier does not create, restore, or finalize business records. A STOP callback for the parent's accidental second agreement `agr_5YSKYz2`, if emitted, proves only that agreement's notification path; it must not be presented as provider agreement-creation idempotency. The original paid test agreement is `agr_Un4JzLG`. Provider reads and business reconciliation are evidenced separately by the parent.

## Cleanup

Completed at 2026-09-09T08:27:34.326382+00:00. Provider deletion returned 204; GET confirmed registration `58e21a30-68d3-455d-886c-a9427d2cecea` absent. There were no pre-existing registrations, and the final registration list is empty. Owned server and tunnel processes exited. Eight technical receipts were exported to `receipts-final.json` before dropping only `talli_192_webhook_ea3801ae` and `talli_192_webhook_358bfa5a`; catalog queries confirmed both absent. Shared test database and provider payment resources were left under the parent verifier's control. See `cleanup.json`.
