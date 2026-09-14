# Accounts test environment recovery

Both independent reviews close the backend-binding administration finding.
Their original reports and SQL probe are adopted without modification.

The complete gate at 8a5565be passed credential scanning, type checking,
architecture validation, backend/web/API boundary checks, both production builds
and boundary smoke. It stopped during an Investments database rehearsal when
the local Docker VM could not write PostgreSQL WAL because its disk was full.
The complete original failure log is retained; this is not a gate pass.

Recovery selected only unattached anonymous PostgreSQL volumes created during
three previously recorded #152/#153 gate windows and carrying the talli_test
database catalog marker. All 39 volumes were archived locally with metadata,
verified archive contents and SHA256 before deletion. The private 337 MiB backup
is retained with mode0600; its path/digest are recorded. Active, named and
unmatched volumes were untouched. Approximately 2.4 GiB was recovered.

Nine existing disposable database harnesses now explicitly remove anonymous
volumes when removing their own generated container names. Their business
assertions are unchanged. The failing Investments rehearsal passes and its
before/after volume inventory is identical, proving no new orphan volume.

The separately completed architecture suite had 57 passes and one stale expected
edge list. That list now includes the declared Accounts source workflow; the
focused failed check passes. No failing assertion was removed.

The complete gate and real Accounts browser journey remain pending; no stage
exit, hosted application or production provider authority is claimed.
