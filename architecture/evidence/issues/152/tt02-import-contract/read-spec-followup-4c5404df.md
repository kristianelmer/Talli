# #152 filing-read Spec follow-up: 4c5404df

**PASS for the bounded correction. SPEC-152-READ-1 is closed; no new actionable finding.** Reviewed `b1bf9e9f7b5697226815a603743dc58e2b751e83...4c5404dfcedfbd5b858d76e1a7095ec2bd800247` using immutable committed bytes, excluding uncommitted drafts.

`CompanyTaxFilingRows.__post_init__` now requires every one of the six families to be a list or tuple before recursive freezing. Empty objects and strings consequently raise `COMPANY_TAX_DEPENDENCY_UNAVAILABLE` at the owned public boundary, satisfying the source rule **“Missing source is unavailable.”** The existing company/year/obligation/reference validation remains unchanged.

The original twelve independent regression cases pass unchanged against the fixed source. Together with the 38 committed workspace/API cases, independent verification reports **50 passed in 5.11s**. Separate controls confirm that populated list and tuple families both remain accepted, become immutable tuples, and preserve the imported nested receipt hash. Existing tests also verify recursive immutability and HTTP preservation of nested receipt JSON.

The diff contains only the two-line production guard, two new committed malformed-input cases, and four evidence files. The SQL read contract, adapter, named workflow, API, generated-client generator/output, and OpenAPI are byte-identical to the previously reviewed milestone. All three adopted artifact hashes match; requirements and all six pending criterion states are unchanged.

This closes a public-contract shape defect that the existing HTTP model already blocked. It does not extend the earlier SQL evidence: those 45 recorded checks used synthetic claims and a rollback-only temporary phase change. No database, browser, provider, repository, or shared configuration mutation was performed. UI/cutover/mutations, yearly production completeness, rollback rehearsals, complete gates and protected integration remain pending; this is not full-stage acceptance.
