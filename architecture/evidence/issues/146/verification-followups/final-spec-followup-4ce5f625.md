# #146 Archive inventory Spec follow-up

**PASS — no actionable findings.** Reviewed `7186841f3286c53fdb5c838963703de0efac17cc...4ce5f625c95ea14bb188c4169814130b3327e2ff`.

The source inventory replaces only `holding_actions` with `company_tax_filing.settlements`, retaining its year scope and every other source. This matches the existing Tax cutover, which moves the Archive generation trigger to canonical settlements. The static test derives that trigger from the actual shipped cutover SQL and checks the owned Tax source read occurs between Archive begin and complete. The update preserves the requirement to retain source completeness and generation boundaries without adding a compatibility exception.

Independently ran only `tests/company_access_cancellation_schema.test.mjs` from an outside-repository archive of the pinned commit: **16 passed, zero failures/skips,64.688792ms**. Verified the executing runtime reports **Node24.20.0** at `/Users/kristianelmer/.codex/issue-192-private/runtime/node-v24.20.0-darwin-arm64/bin/node`; its binary hash and all test inputs are bound in `final-spec-followup-4ce5f625-bindings.json`.

Previously adopted Spec report and bindings are byte-identical to the private originals. Other added files are review evidence. No runtime business source or migration changed in this delta. No repository, database, browser, Git-state or generated-file mutation occurred. The independently running full fresh aggregate and complete immutable gates/protected integration remain unaccepted by this bounded review.
