Spec review: authority workflow ownership 39b72c60

PASS for the single-commit `git diff 32c701e3...39b72c60`; no actionable Spec finding.

The TT02 adapter retains its fixed endpoints, validation, redaction and transport behavior. Independent AST comparisons verify all 18 transport methods (allowing only relocated shared imports), both transport helpers, all three polling bodies, and the unchanged CLI credential composition, CLI error presentation and safe-summary function: 26 definitions total. Shared transport/payload mechanisms and Annual Accounts implementations remain byte-identical.

The owned prepare/resume workflow retains the reviewed ordering: validate approved test scope and identity, persist initial intent, then check credentials and connect. Completed replay returns before credential acquisition. Existing-instance recovery, exact invalid-party repair, current-reference conflicts, upload/validation checkpoints, retryable failure classification and read-only receipt resume follow the predecessor branches. The port exposes the human confirmation URL/handoff but no operation completing the user’s final confirmation. This supports GH-152-A3’s requirement that transitions “remain authorized and idempotent” within the existing local test workflow; it is not production authorization or complete stage acceptance.

I independently ran 254 focused tests in two invocations: 246 authority transport/tool/rehearsal cases and eight payload cases, all passing. These use mocked provider responses and private local fixtures; no provider call occurred. The 108 predecessor year cases also reproduced byte-for-byte, with the exact decoder source hash verified. Their public-workflow tests assert accepted inputs write intent before credentials and invalid inputs cause neither checkpoint nor provider acquisition.

All nine source bindings and five evidence artifact hashes verify. The adapter registrations, public contracts and MODULE description match the bounded relocation; original issue criteria remain unchanged. The old Tax transport implementation is removed rather than retained as another active implementation.

No new HTTP/browser stage-exit proof, durable production history/completeness, provider activation, hosted change, full release gate or successor acceptance is claimed. Those remaining requirements stay outstanding.
