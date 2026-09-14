Spec follow-up: authority summary immutability 699f4dfa

PASS for `git diff 39b72c60...699f4dfa`; the nested-summary aliasing finding is closed, with no new actionable Spec finding.

The public workflow now applies the existing recursive, detached fact freezer to its result. Nested dictionaries become read-only mappings and arrays become tuples, so later mutations of IO-owned evidence cannot alter the returned summary. The CLI’s explicit thaw recreates ordinary dictionaries/lists, preserving accepted predecessor structured JSON fields rather than rejecting or relabelling them. This satisfies the public immutable-fact boundary while retaining GH-152-A3’s replay behavior.

Independent validation: all 256 authority, rehearsal and payload checks pass. Against the pinned predecessor, the two new completed-replay tests produce one expected immutability failure and one CLI compatibility pass. On the correction, both pass, including mutation rejection, source detachment and no credential/provider access during completed replay. An additional unchanged private probe with 600 nested arrays succeeds on both revisions and emits a serializable summary. That is a bounded depth check, not an unlimited nesting guarantee.

The prepare/resume state machine, polling bodies, TT02 adapter, shared mechanisms and original issue requirements are byte-identical across this correction. No authorization, persistence ordering, human confirmation or provider behavior is added. All four source bindings and six evidence artifact hashes verify; the earlier review remains a historical checkpoint rather than being rewritten as complete immutability proof.

Verification used exact private source archives and synthetic files with no shared checkout edits, database, browser or provider operations. Full HTTP/browser verification, durable history/completeness, release gates, hosted activation and full-stage/successor acceptance remain outstanding.
