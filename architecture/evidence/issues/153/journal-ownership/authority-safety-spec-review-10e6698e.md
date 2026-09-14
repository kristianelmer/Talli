Spec follow-up: CHANGES REQUIRED — the two original P2s close; one concurrent-journal P2 remains.

Reviewed exact `eb7d312054c32a8e94dd9d0c8bf9f22dcf9a12fa...10e6698efdcad2726f5ca9f7dcdb7352317ceb11`.

**STD-153-JOURNAL-1, P2:** `rehearsal.py:94–127` reads and saves the shared evidence before awaiting connection, without exclusive ownership of that journal. Two concurrent actual CLI calls using the same real evidence file both reach the provider, create distinct instances and lock them; both return success, but only one instance survives in the file. Atomic replacement prevents partial JSON, not competing writers. This violates #153’s requirement that submission/signing states “remain fail closed and auditable” and #132’s idempotency/retry evidence requirement. Acquire an exclusive journal lease before reading prior state and retain it through effects/checkpoints, or use equivalent atomic claim semantics. Reject the competing invocation before credentials/provider construction. Independently reproduced with actual `annual_accounts_test.run`, `LocalAnnualAccountsRehearsal` and private temporary files; only provider/clock/XML were fakes.

**STD-153-REPLAY-1: CLOSED for sequential recovery.** Saved pending intent prevents another create/lock after lost/malformed responses, interruption or checkpoint failure. Legacy ambiguous states stop before connecting; confirmed locks recover by read-only submission/handoff queries.

**STD-153-VALIDATION-1: CLOSED.** Malformed validation now fails before lock; recognized empty/soft results progress and numeric/named errors block. Lock/handoff require positive signing state. Cached official Altinn enum/model hashes match the committed bindings.

Independent validation: **275 backend tests,16 Archive inventory checks and13 original/file-checkpoint probes pass**; two additional concurrent probes reproduce the open defect. Original frozen traces remain byte-identical. Comparison excludes only added journal metadata/pending saves and explicitly checks the two intended ambiguity-error changes. All46 manifest hashes and15 adopted originals match. Archive scope mapping and failed-gate disclosure remain truthful. Earlier17+7 deployment proofs still apply to unchanged SQL/HTTP paths; they do not certify the altered authority journal.

No shared repository, database, Docker, browser or provider mutation occurred. No power-loss durability claim. Complete immutable gates, real Accounts browser and protected integration remain pending; no full-stage or successor credit.
