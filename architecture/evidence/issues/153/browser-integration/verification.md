# Accounts browser integration and source review correction

The independent source review pair found STD-153-SOURCE-1: retained malformed
feedback metadata could be projected as invented document identities while
history was complete. Original reports and reproductions are adopted unchanged.
The projector now accepts null or an array of text references and fails unavailable
for other shapes. Public and authenticated HTTP regressions pass.

An explicit post-cutover migration binds the restricted backend login to the
Accounts workflow executor with SET and without inheritance or administration.
Its rollback removes the binding. Real rollback-only database verification checks
pre-cutover denial, exact membership, no store-owner access and removal.

Browser fixture seeding and cleanup now use owned Accounts, Tax and RF stores;
the final owner journey verifies the generic filing tables are absent. A new
Accounts browser journey covers pending TT02 evidence import, permission/manual
evidence controls, source scope, source outage and current-role revocation.
It is wired into the complete disposable-stack gate. It has not yet been run.

23 database lifecycle tests,29 source projector/adapter/HTTP tests,20 fixture
safety tests and architecture validation pass. Full architecture tests, real
browser execution, final advisors, independent follow-up reviews and the full
protected stage-exit pair remain pending. No stage-exit credit is claimed.
