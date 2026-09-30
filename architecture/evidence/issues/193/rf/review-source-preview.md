# Source-backed preview review

Reviewed 2026-09-23 against `efbea434d07b5530618dabbeb8645d0208b554dd`.
The reviewed uncommitted source and test bytes are bound in
[review-source-preview.json](review-source-preview.json).

## Standards

No actionable finding remains within the reviewed public contracts, preparation,
workflow, adapter, codec and owned SQL. The new preview history stays separate
from the legacy production path; ownership checks and mutation contracts remain
with their declared capability. Broader manifest/release checks are separate.

## Spec and correctness

No actionable scoped finding remains. Exact source/company/year/case hashes and
canonical rendering are checked before capture. Fresh owner, Documents,
Governance and register facts are re-read through their public contracts; the
current RF source is rechecked under the correction lock before new insertion or
identical replay. Historical previews retain their stored rendering, and source
corrections and rollback preserve prior history. The closed codec rejects
changed payloads and preserves blocked previews with both XML fields absent.

Two concrete review findings were fixed and independently reproduced: paid-in
`2000.005` and registered capital `30000.005` now retain exact digits and produce
identical complete previews under `ROUND_DOWN` and `ROUND_UP`. The shared
renderer no longer introduces a float conversion or ambient rounding for these
review amounts.

Validation: **224 focused offline tests passed** in 0.95 seconds across source
preview, authenticated preview/source/capital workflows, source codec,
preparation, rule equivalence and offline equivalence. `git diff --check` passed.
The reviewer made no implementation edits to this delta. SQL and its runtime
tests were inspected; separate persistence evidence owns the actual DB runs.

This is bounded preview foundation evidence. It does not establish full RF
acceptance, genuine-company/provider acceptance, complete archive integration,
customer routes, approval/send activation, or a cross-owner serializable lease.
