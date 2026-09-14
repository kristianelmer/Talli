# #152 TypeScript Tax policy retirement — Standards review

**PASS — no actionable standards finding.**

Immutable scope: `git diff 6353c78cdc32700b92c1431732d9e782fba5612a...32c701e31ff83016342c47a74ab0951ba3eab05d`; one policy-retirement commit. Applied the existing code-review Standards axis, AGENTS/CONTEXT/domain guidance, ADR0011–0013, capability ownership and supplied heuristic smell baseline. No heuristic override of repository rules.

The five deleted production Tax implementations have no remaining production imports. The shared `authority-test-evidence.ts` retains exactly sixteen shared/Annual definitions: independently compared complete TypeScript AST source bodies against the predecessor and verified every recorded hash. No Annual behavior or shared helper changed. This removes duplicate Tax policy in accordance with capability ownership rather than adding a production compatibility facade.

`tests/support/company_tax_public.mjs` and its fixed Python driver are test-only consumers of the actual Company Tax public package. Dispatch is a finite operation list; no arbitrary import/file selection, provider, HTTP or persistence path is introduced. Input/output sizes and subprocess duration are bounded. Existing payload, submission, XML, Tax estimate and Investments cross-output inputs/assertions remain. Supabase test changes only rebind imports. The obsolete action assertion now checks the authenticated Tax API/error boundary; predecessor SQL assertions remain, explicitly labelled.

Independent isolated **Node v24.20.0: 41/41 PASS, zero skips**, including official XML validation against clean schema checkout `7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba`. Actual pinned Python public source was imported through a no-bytecode wrapper. An initial missing isolated client-package symlink was corrected to the extracted pinned package; its setup-failure transcript is retained separately. All five deleted-source hashes and three artifact hashes match the retirement manifest.

No database/browser/provider operations or shared source/config edits. Recorded typecheck/architecture results were inspected, not rerun here. This bounded cleanup review does not certify the remaining workflow, full gate, cutover or #152 exit.
