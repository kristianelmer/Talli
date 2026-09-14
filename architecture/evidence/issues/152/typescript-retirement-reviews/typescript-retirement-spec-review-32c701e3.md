Spec review: TypeScript Tax retirement 32c701e3

PASS for `git diff 6353c78c...32c701e3`; no actionable Spec finding.

The five deleted production files and removed shared helpers are Tax-only implementations now served by the owned public contracts. Their predecessor hashes match the manifest, and no production consumer imports the new test bridge. This advances GH-152-A5’s requirement to remove “duplicate TypeScript calculations” without introducing a production compatibility facade. It does not establish completion of the entire criterion or stage.

I independently compared all 16 retained Annual/shared declarations using TypeScript AST source text: every retained body matches the predecessor and the recorded hashes. Shared imports remain intact. The existing payload, submission, XML, Tax estimate and Investments cross-output fixtures retain their inputs/assertions and now execute real Python public contracts through a fixed four-operation test driver. The driver performs transport/representation conversion, not a second tax calculation or stored-fixture lookup. Supabase changes only rebind imports; no database test result is inferred.

All 41 focused checks pass independently with no skips, including rendering and validating XML against the clean official schema checkout at `7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba`. The obsolete action-source assertion now targets the implemented authenticated API and stable error presenter; historical SQL checks remain explicitly labelled as predecessor behavior. This static assertion does not replace real-action/API tests from earlier milestones.

All three retirement artifact hashes and five removed-source hashes verify. Original issue requirements remain unchanged. Testing used exact committed source in a private archive with pinned Node 24.20.0 and the existing Python runtime; no shared source, database or browser mutation occurred.

Provider workflow ownership, complete source handoff, durable rollout verification, full gates and protected integration remain pending. No full-stage, provider, hosted or successor acceptance is granted.
