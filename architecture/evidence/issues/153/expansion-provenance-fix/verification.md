# Accounts retained setup provenance fix

Independent Spec review of 04e682b6 reproduced cross-company and wrong-year
opening setup references passing the original classifier. This fixes
SPEC-153-EXPAND-1 without changing the earlier evidence or its original hashes.
The expansion now snapshots only referenced setup IDs and company/year under
the RF store owner and a write-blocking lock. A temporary owner SELECT policy
is created and removed inside the same migration transaction. No runtime
cross-owner access is added. Missing or conflicting setups quarantine the
Accounts preview or submission; a preview's quarantine propagates to all
submissions, overrides and comments. Null references remain supported.

The exact revised SQL was exercised on a separately restored disposable clone.
Six conflicting rows quarantine. Matching and null preview and submission
controls remain copied, all six count/hash reconciliations pass, source rows
are unchanged, and RF table ACL/policies and global memberships are restored.
The expanded control fixture first hit the existing one-submission-per-preview
constraint; its failure is preserved and the final fixture uses distinct previews.
The populated 60-role-access/seven-classifier suite and unknown-family quarantine
suite also pass against this SQL. All probe transactions roll back. The clone is
retained for subsequent read/control rehearsal; it has no Accounts schema yet.
The earlier lifecycle clone still contains the previous inactive expansion;
no active writer, hosted database, provider or production deployment changed.

This is a bounded migration correction. Read/write contracts, cutover, rollback,
web workflow and full #153 stage-exit verification remain pending.
