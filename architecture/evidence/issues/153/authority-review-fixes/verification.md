# Authority review follow-up

Spec review found two P2 input-boundary regressions in 50bfe67a. The removed Node
bridge accepted false, zero, negative zero and empty-string Annual data as absent.
The new Python mapping now preserves those scalar cases while leaving nonempty
values and empty arrays/objects subject to the original shape failures. The
original bridge rejected a non-array ledger value; the new mapping now rejects
every non-null, non-list JSON value before entering the typed source contract.

The reviewer reproduced both findings through the actual old Python-to-Node
subprocess and retained ten full old/new outcomes. Those exact results now drive
regression tests. Both review reports remain unchanged, with findings retained.
The first regression test run used the wrong error-capture wrapper for two old
failures; correcting only that wrapper made all ten match. The full 236-test
Accounts/Tax authority suite passes, including the previous 226 checks.

No workflow guard, checkpoint order, HTTP body, credential path, persistence or
live web caller changed in this fix. Database expansion is separately under
construction and is not included in this revision. All six stage criteria remain
pending; this is not an exit receipt.
