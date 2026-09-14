# #152 CLI Spec follow-up: af95066f

**PASS — both CLI parity findings are closed; no new actionable finding.** Reviewed fixed `c3eb992c30531f7402a31ceb830164fa4fda1654...af95066f0655733b8ea76ef1490b3178864aced7`, retaining original `8b3e0cb340d962c8140b1ac72ceada59d4d4aea7` CLI results as the comparison baseline.

SPEC-152-CLI-1 is closed. The CLI mapping preserves explicit JSON null as a present empty reference, so the existing Tax validation rejects it for both envelope operations. Omission still permits an envelope without the reference; empty and valid-string controls retain their original errors/bytes. The correction stays at transport mapping and introduces no second validation policy.

SPEC-152-CLI-2 is closed. Calendar-date interpolation uses the existing JavaScript string-rendering helper. Integral `2025.0` again produces exact legacy `2025-01-01` and `2025-12-31` XML dates. The committed regression binds the complete two-document statutory hashes.

Independent isolated execution passed **313 tests**: 157 pure comparisons, 146 mocked-provider authority cases, and all ten original independent CLI probes. A fresh run of the unchanged probe script against pinned af95066f produced byte-identical complete result/error JSON to the original 8b3e0cb3 capture. The prior three failures now pass without weakening the seven controls.

The change comprises the two implementation corrections, their targeted tests and historical review/test evidence. Evidence adoption hashes match; the six requirements and existing pending status are unchanged. I did not inspect the uncommitted SQL draft or accept API/web/persistence cutover, full-stage gates, protected integration or provider validation. Tests used private pinned sources, standalone CPython 3.12.12 and pinned Node v24.20.0; no shared repository, database, browser, configuration or provider mutation occurred.
