Spec review: derived Boolean follow-up c9c2b30e

PASS for `git diff 6d42211f...c9c2b30e`; the derived-output defect is closed and no new actionable Spec finding was found.

At `calculation.py:205`, Python `bool()` still converted an empty array/object in `no_activity_confirmed` to false for `derived.noActivity`. The preceding review verified feedback/readiness conditions; it did not establish full derived-output equivalence. Replacing this conversion with `truthy()` now preserves the predecessor’s `Boolean()` result, consistent with GH-152-A1: “Supported company-tax cases produce outputs identical to current schema and TT02 evidence.”

I independently reproduced the expanded 45-case capture byte-for-byte with pinned Node 24.20.0 and verified predecessor source bytes. The capture uses the unchanged Boolean inputs and compares complete schema, derived values, fields and feedback. Supplying the original `companyPartyNumber` in the test’s public source construction correctly preserves the reference fields. With the new comparisons against pinned 6d42211f, exactly the two empty-container no-activity cases fail (43 pass); on c9c2b30e, all 391 readiness, characterization and original HTTP regression tests pass. The committed 388-test transcript is separate historical validation and matches its manifest hash.

The only product change is the single Boolean conversion. All six adopted evidence artifacts and both the new capture and input/source bindings verify. The prior input capture, prior manifest and six issue criteria remain byte-identical. The expanded capture strengthens parity evidence without changing earlier recorded results.

This closes the demonstrated derived flag discrepancy, not an exhaustive arbitrary-input equivalence claim. Uncommitted web callers, source-backed completeness, durable cutover, provider workflows, full gates and protected integration are outside scope. No hosted, provider, full-stage or successor acceptance is granted.
