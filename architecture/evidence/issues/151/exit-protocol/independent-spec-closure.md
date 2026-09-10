# Independent Spec closure: RF deployment-order protocol gap

Candidate `dd1a7dba8192746f5e882d5b119d895bf7730ce1`; predecessor `91b178c281bcc5fb887a6257d2f72e380199f3e6`. This supplements the unchanged historical `/tmp/talli-151-envelope-mapping.md`.

**The identified local RF protocol evidence gap is closed. No further unproved local item was identified beyond remaining receipt storage, second linked complete gate and protected integration.** This is bounded Spec acceptance, not full-stage or production acceptance.

I inspected the protocol README, per-case results and source manifest. The independent agent run passed29checks using Node25.6.1. Root repeated the unchanged harness with Node24.20.0; that result also records29passes/0failures. I verified both pinned revision identities and all318 extracted source SHA256 values in each run. I did not execute either run.

The proof uses exact predecessor/candidate generated clients and transports against their actual FastAPI applications with existing local CoordinatorSession ports. Retained Send/recovery preserve method/path/body, bearer/correlation, no-store and response validation. Repeat Send retains operation IDs/body hashes; unknown outcomes do not cause a second mutation; token/auth failures cannot begin. All11 current preparation wrappers receive the actual prior-app missing-route404 and reject it without the owned-not-found code. Six exact current action bodies use real transport and fail without public-table/audit effects or success redirects.

This proves the intended distinction: retained Send/recovery remain compatible; new preparation operations fail safely until the expanded backend is deployed. It does not promise uninterrupted obsolete preparation UI after SQL cutover. The sequence deploys expanded backend first, quiesces old direct preparation writers before canonical cutover, and contracts last. Persisted one-journal identity, rollback and legacy writer barriers remain covered by separate SQL/gate evidence, not local ports.

The first complete gate is independently verified11/11 in `/tmp/talli-151-gate1-independent-review.json`; mandatory130-case RF/authority DB and historical11/fresh12 browser lanes pass without skips. Previously disclosed optional skips remain disclosed there. Protocol runs are supplementary evidence, not extra gate checks. No DB/browser/provider operation or repository edit was performed by this reviewer. No hosted/provider activation or full #151 exit is claimed.

## Bindings

- `/tmp/talli-151-rollout-protocol-dd1a7dba/results.json` SHA256 `6b28844021b1565f4e9d300113e2f1137d6c630968453e5347a64f9c29c3ab39`.
- `/tmp/talli-151-rollout-protocol-dd1a7dba/source-manifest.json` SHA256 `279ee7e974509304a15578f93f9b2a63a67e19db3c944b6928796f7784e5ce5d`.
- `/tmp/talli-151-rollout-protocol-dd1a7dba/transcript.log` SHA256 `fa50d7a4bbee42ab2857cb57f0863072350b8595bf13a3305af9efdb1ccc2c98`.
- `/tmp/talli-151-rollout-root-node24/results.json` SHA256 `3eb475d62a679dc972115f6a8fbe8c39f2da05538e5df62905a726d5665b29af`.
- `/tmp/talli-151-rollout-root-node24/source-manifest.json` SHA256 `279ee7e974509304a15578f93f9b2a63a67e19db3c944b6928796f7784e5ce5d`.
- `/tmp/talli-151-rollout-root-node24/transcript.log` SHA256 `fa50d7a4bbee42ab2857cb57f0863072350b8595bf13a3305af9efdb1ccc2c98`.
