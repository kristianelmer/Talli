Spec follow-up: server-action directive f9838c60

PASS. SPEC-152-ASSESSMENT-CONSUMERS-1 is closed at `f9838c6096640d9810381d86ef64dd8177ee35ac`.

The new import now follows the `"use server"` directive in `apps/web/app/actions.ts:1–3`. I independently compiled the exact committed module using installed Next 16.3.4 SWC with pinned Node 24.20.0 and verified emitted server-reference registrations. The same compiler still rejects the exact predecessor module, providing the negative control. The added regression compiles the whole real module rather than only extracted action bodies.

All 42 focused composition/readiness/payload tests pass, including the new compiler check. After removing the relocated import line, predecessor and corrected action files are byte-identical: refresh bodies, scopes, source failures, persistence ordering and compatibility digests are unchanged. The only other changed file is the compiler regression test, and issue requirements remain unchanged. This restores the executable server-action boundary required by GH-152-A4 without broadening the previous consumer review.

No new actionable Spec finding. Verification is a focused compiler/test exercise, not a full Next build, browser journey, provider execution, SQL cutover, immutable gate or full-stage acceptance. Uncommitted parent work remains excluded.
