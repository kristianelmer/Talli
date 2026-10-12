One P2 finding: STD-193-RF-CONFORMANCE-1 — bind optional system-user delegation before key access.

The approved-plan configurationBindings omit TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF, while CliGrantConfiguration.from_environment reads it and build_cli_grant includes a supplied value in authorization_details. The exact main configuration predicate therefore accepts both the planned absence and an added/different system-user external reference under the same plan digest. This conflicts with the plan’s exact configuration-before-credentials stop condition and the repository’s bounded credential-action authority.

A pure reproduction evaluates the actual main guard extracted from the frozen source, then invokes the actual CLI claim builder with synthetic configuration. Both configurations pass but produce different delegation claims. No key was read or used, and no token/provider request occurred. Bind the optional value or its explicit absence, or bind the complete configuration bytes, before credential access.

Other bounded checks cover exact URLs/methods and counts, expiry, private file creation, checkpoint-before-request failure, cancellation after the first token, and no-approval/source guards. Mock tests pass; they do not confer execution authorization. The original script and plan remain frozen, with complete hashes in JSON. Spec separately owns the early receipt-hash mismatch stop condition.

No live action, browser, hosted write or provider/key access was performed. This review is preparation only and currently requires correction, not RF/#193 completion.
