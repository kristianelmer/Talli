# Annual owner fixture after Tax filing contraction

Complete gate ac9b349ab58b89bdd0efa4810ef382844be5c6fa passed the 32 Tax database cases and contracted the filing schema, then correctly rejected the annual browser fixture's old public Tax permission insert. It has zero complete-gate credit. The same failure reproduced in the focused real annual owner browser.

The fixture now requires contracted Tax filing state and inserts the same synthetic permission into company_tax_filing.authority_permissions through finite fixture access. It verifies that no legacy Tax permission mirror exists. Accounts and the historical RF fixture remain unchanged. Cleanup includes all six named Tax filing families in dependency order, preserves foreign-key checks and restores temporary grants/triggers. The actual browser assertions are unchanged.

The focused annual owner browser passed (one test, zero skips). The fixture and process suite passed 22 tests with its existing optional live database test skipped in this configuration; this focused run is not full-gate credit. The remaining final lanes (RF feedback, Authority browser, fresh RF browser and both Tax browser journeys) passed against the contracted retained local database; no mandatory journey skipped. The next complete gate remains pending.

Independent whole-stage reviews at ac9b349a found no actionable implementation gaps. These are prior-source reviews; the four test/support-file changes in this follow-up require their own bounded review.
