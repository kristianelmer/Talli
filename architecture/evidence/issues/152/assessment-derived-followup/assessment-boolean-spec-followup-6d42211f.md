Spec follow-up: 6d42211f against 497b91d8

PASS for this bounded correction; no new actionable Spec finding.

The remaining direct pure/CLI Boolean-parity concern is closed for the reviewed conditions. `numbers.truthy` preserves ECMAScript conversion for empty arrays/objects, strings, null, Boolean values, zero and nonfinite numbers. `calculation.feedback` applies it to annual loan/dividend/share answers, warning acknowledgement and no-activity; `readiness.assess` applies it to settlement readiness. Ordered messages and deduplication remain unchanged. The classified-dividend fallback also now uses the predecessor’s Boolean condition. These changes support GH-152-A1 (“Supported company-tax cases produce outputs identical to current schema and TT02 evidence”) and A2’s deterministic fail-closed requirement.

I reproduced all 45 frozen predecessor Boolean cases byte-for-byte using Node 24.20.0 with verified source hashes. Against pinned 497b91d8, those cases reproduce exactly 10 failures and 35 passes; against 6d42211f, 390 readiness, characterization and original HTTP regression tests pass. A separate 21-value comparison against Node’s Boolean conversion passes, including frozen empty containers, NaN, infinities and negative zero. The public preparation contract used by the CLI retains the loan block for empty arrays/objects; this is not a provider or end-to-end CLI execution claim.

The HTTP request boundary now rejects missing/null ledger accounts before calculation. Tests verify both rejected inputs and the valid `7770` control returning the expected cost; prior malformed-container and Boolean rejection remains passing. No persistence, authorization, generated route or source-completeness behavior changes in this follow-up.

All nine committed manifest artifacts, capture hashes, and predecessor-source hashes verify. The six issue criteria are unchanged. The recorded 463-test combined run is historical evidence inspected by hash, distinct from my 390-test run. Web callers, source-backed production handoff, SQL cutover, full gates and protected integration remain outside this review; no hosted, provider, full-stage or successor acceptance is granted.
