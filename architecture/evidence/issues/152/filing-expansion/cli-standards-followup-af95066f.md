PASS — the explicit-null Standards finding is closed at `af95066f0655733b8ea76ef1490b3178864aced7`. Reviewed the bounded correction from `c3eb992c30531f7402a31ceb830164fa4fda1654`, retaining original CLI baseline `8b3e0cb340d962c8140b1ac72ceada59d4d4aea7` and the prior Standards rules/baseline. No new actionable finding.

`company_tax_payload.py:25–29` preserves explicit-null presence by mapping it to the public contract’s empty-string case, so the existing Company Tax required-reference validator rejects it. Omission remains distinct, and the transport still presents the generic redacted failure. This is a transport representation correction; validation policy remains capability-owned.

`calculation.py:193–194` uses the existing ECMAScript numeric-text helper for date fields. Independent dispatch comparisons confirm that both integer `2025` and JSON integral float `2025.0` produce exact predecessor tax/business XML and feedback. It does not introduce a new year policy or alter the valid date format.

Reran the original eight-case null/reference probe against exact predecessor Node dispatch and pinned candidate `_filing.payload`: both envelope operations reject explicit null/empty, accept omission and accept a valid reference. Added independent exact-year comparisons. The 241-test isolated run passed all 157 pure characterization cases and 84 focused authority/CLI cases. The broader 303-test mocked-provider result is independently hash-bound recorded evidence, not a claim that this review reran all 303.

All five adopted artifact hashes match. `_filing.py` and the retained Annual Accounts Node dispatcher are byte-identical to the prior reviewed checkpoint, preserving its limits, redaction and sibling behavior. New regression tests cover missing/null/empty/whitespace/valid references and the integral-float statutory hashes. The manifest still marks API/web/SQL/full-stage exit pending.

Only pinned Git objects and an isolated temporary extraction were used. No shared DB, browser, configuration or tracked source was changed. Uncommitted SQL expansion is excluded; this grants no complete gate or #152 exit credit.
