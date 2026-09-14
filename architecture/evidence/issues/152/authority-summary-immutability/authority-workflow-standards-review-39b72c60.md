# #152 authority workflow — Standards review

**CHANGES REQUESTED — one P2 public-contract defect.**

Pinned scope: `git diff 32c701e31ff83016342c47a74ab0951ba3eab05d...39b72c60ac941e92083dddfc503927a1653cb173`; one commit. Applied the existing code-review Standards axis, AGENTS/CONTEXT, ADR0011–0013, module/system ownership and supplied Fowler heuristics. No heuristic overrides repository standards.

**P2 — public summary remains mutable and aliases private replay evidence.** `apps/backend/src/talli_backend/modules/company_tax_filing/public.py:644` wraps only the outer summary in `MappingProxyType`. `rehearsal.safe_summary` copies metadata references directly, while the local evidence loader accepts nonempty JSON objects without constraining these summary fields. Independently reproduced a completed `resume` with `authorityValidation.result={"value":"original"}`: assigning `result["validationResult"]["value"]` succeeds and changes the IO-owned prior evidence. No credentials or authority connection is reached. This violates ADR0011's immutable public-contract rule and MODULE.md's explicit immutable-summary claim. Detach and recursively freeze the returned data, or validate/project immutable summary values; preserve CLI JSON serialization. This finding concerns accepted structured replay metadata, not ordinary provider responses or a new provider-security claim.

Otherwise, transport mechanism and policy ownership are separated through declared ports/adapters; the CLI delegates ordered prepare/resume decisions, and shared Annual mechanics remain unchanged. The old Tax transport file is removed. Independently compared all eighteen transport method ASTs (normalizing relocated imports) and all three polling bodies: unchanged.

Independent isolated execution: **254/254 PASS**, using actual pinned Python source and Node24 where subprocesses are required; provider responses are mocked. Reproduced all 108 predecessor year captures byte-identically and verified all fourteen manifest source/evidence hashes. The generic test/HTTP adapter is not a new production endpoint, and no hidden provider submission or human-confirmation operation was added.

No shared checkout/config edits, database/browser/provider calls or full-gate/stage-exit credit. Exact bindings, test transcript and the executable immutability probe are retained beside this report.
