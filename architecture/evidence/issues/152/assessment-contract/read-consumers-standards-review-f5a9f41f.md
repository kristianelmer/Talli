# Standards review — owned Tax read consumers

**PASS: no actionable Standards finding.** Reviewed `6ab578f8d2afb02544a23ab685800d120764a5cc...f5a9f41f79ff54c5d2a4b9d58b8ab67d77419115`, one commit, 20 changed files. Subsequent Tax policy work is excluded.

The feature presents generated Tax DTOs without introducing persistence or calculation policy. Nested receipt/call/feedback/payload-reference extension fields survive, while malformed source values produce explicit unavailability. One complete read per company supplies all six families; a failed company discards partial Tax results. Workspace and annual workspace preserve identity-based composition and ordering; annual workspace includes Tax among mandatory source errors.

Archive includes Tax-only submissions and only authority evidence linked to selected-year Tax submissions. Readiness uses the owned previews, submissions, overrides and permissions. Both stop before result/snapshot/receipt production on a Tax source failure, preserving retained sibling persistence and existing Audit behavior.

The strengthened checker independently requires exact historical/current source composition and every retained original persistence chain for Archive and readiness. Earlier completed deletions therefore cannot authorize a different body. New hashes remain restricted to #152 or completed Tax with its old facade absent; historical #146 hashes remain unchanged. The registry and frozen baseline are byte-identical. These controls satisfy ADR0013’s bounded migration rules without broadening compatibility authority.

Independent isolated **Node24.20.0 verification passed 48 consumer tests and the expanded guard matrix**: 28 body mutants across seven operations, plus earlier-stage/restored-facade controls using actual original and completed-gate source callbacks. All seven evidence artifact hashes and both new AST composition digests match. ADR0011–0013 and the retained heuristic smell baseline yield no additional finding.

The tests use real functions with dependency doubles. No shared repository/runtime/database/browser mutation, real HTTP/JWT/MFA, provider call, durable cutover, full-stage or release-gate verification occurred. Exact source and transcript bindings accompany this report.
