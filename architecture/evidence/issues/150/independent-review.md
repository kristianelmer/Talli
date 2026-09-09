# Independent review of #150

Base: `b30312de11ad942479421def243e4a2252fbf166`.
Implementation: `11633707c3227c01aa8f2153f28d4e199bf64df1`.
Browser successor: `bef98825`.
Corrective review: `ff8f3c50e3543d39dcc245b18acaa89feb4bf903`.
Final fixture delta: `c9a7f4e6752b837d0ee58624548b984ecbafe37e`.

The Standards and Spec reviewers ran separately against these fixed diffs.
They used #150, #132, the two owner-approved relocation amendments, AGENTS.md,
CONTEXT.md, ADR0010–0013, the module/architecture contracts and applicable
Copilot guidance. Review used source inspection and bounded local reproductions;
it did not invoke an authority provider or certify deployment.

## Standards

One documented breach was found at the implementation revision: the new
Maskinporten, System User and operator-registration decoders rejected leading
UTF-8 BOMs accepted by their predecessors, contrary to ADR0010's observable
behavior requirement. Corrective review closed it. System User keeps fatal
UTF-8 decoding; registration strips its BOM; the distinct operator callback
continues to retain and reject a BOM. Malformed-byte and response-bound behavior
is covered for each branch.

No additional actionable heuristic smell or documented boundary breach was
found. The browser successor preserves local transport guards, cookie-bound
callback authority, historical RF recovery, receipt integrity, owner isolation,
cleanup and the predecessor's health and accessibility checks. The corrected
harness preserves every predecessor lane, failure propagation and final
successor verification. The final fixture claim matches the production
verifier and changes no permission or business assertion.

Final source verdict: **closed; no outstanding Standards finding**.

## Spec

Two P2 findings were found at the implementation revision. The provider decoder
regression above violated behavior preservation. Separately, strict Python UTF-8
encoding rejected an inline RF archive containing a lone surrogate before
storing/classifying it; the predecessor's TextEncoder stored U+FFFD replacement
bytes. Both findings are closed by the corrective source and regressions.
RF transmitted bytes, hashes, artifact references and stored feedback now use
the same original encoding semantics.

No additional actionable finding was found in the browser or final fixture
deltas. Strict JSON corrections preserve the predecessor rejection of bare
NaN/Infinity constants without changing valid input coercion or existing HTTP
fallback behavior. The scanner fixture markers remain byte-equivalent. Original
intent/UUID continuation, response ordering, historical recovery and approved
ownership boundaries remain preserved.

Final source verdict: **closed; no outstanding Spec finding**.

Standards: one finding, resolved. Spec: two findings, resolved.

## Independence and validation boundaries

The Standards reviewer independently covered the AU public/service/operator
implementation, main provider adapters, root API/web/callback/launch code,
tax/accounts tools and the browser successor. That reviewer authored the AU
database/state workflow and private token/RF tools, so those were independently
covered by the Spec reviewer. The Spec reviewer authored the AU service/operator
and tax/accounts tools, which the Standards reviewer covered. Both reviewed the
other agent's frozen RF implementation and the root's integration changes.

Earlier command reviews resolved five reproduced relocation regressions before
the implementation snapshot. Integration then added strict JSON syntax checks,
kept synthetic scanner markers byte-identical, restored the predecessor database
topology before frozen consumers, and corrected a test-only verified actor claim.
The latter passed all 37 Billing runtime cases on the shipped rollback topology.
No SQL privilege or authorization gate was weakened to make that fixture pass.

This source review does not certify the complete database lane, two immutable
exit gates, protected integration or exact-main Release/Preview. Those remain
separate acceptance evidence in `requirements.json`; #150 and #192 remain open.

## Packaged artifact correction

The complete gate at `67901fd0f2534772110e68f99290136a88280319` failed
because the wheel importer could not resolve `talli_backend.compatibility`.
An independent narrow review checked the added `compatibility/__init__.py`: it
contains only a docstring, with no imports, registrations, provider effects or
authority changes. Read-only ZIP inspection confirmed the initializer and frozen
RF coordinator are present in the rebuilt wheel with exact source bytes. The
existing built-artifact smoke then passed both deployment orders and backend
failure isolation (1 passed, 0 skipped). No source finding remains. The failed
gate is retained separately and receives no exit-gate credit.
