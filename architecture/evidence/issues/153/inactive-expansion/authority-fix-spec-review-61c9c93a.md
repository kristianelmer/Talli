Spec follow-up: **PASS; both P2 findings closed**, no new actionable findings.

Reviewed the single commit in `git diff 50bfe67a17faf3bab714a51372a85d7e16886671...61c9c93add0cfd0011bd55e8f71200eaf8a76a43`. #153 A1 requires “Supported annual-accounts cases produce outputs identical to current schema and TT02 evidence.”

- **SPEC-153-AUTH-1 closed** at `authority_tools/annual_accounts_payload.py:8–12`: only false-like Annual scalars become absent. False, zero, negative zero and empty string recover the original XML/default behavior. Empty arrays/objects and `true` retain their original generic failure.
- **SPEC-153-AUTH-2 closed** at the same file, lines 13–15: non-null, non-list Ledger input is rejected. Empty objects/strings no longer produce zero-balance XML; null and empty-array controls preserve their distinct accepted defaults. The outer fixed payload wrapper retains the original generic error message.

Independent isolated checks: **236 authority tests passed**; the original **10 actual predecessor Node-subprocess cases** all match the fixed implementation; the broader **195-case** edge corpus has zero differences. **Eight old/new rehearsal cases** also match: false-like Annual values and null write identical prepared evidence before an injected credential-stop; arrays, objects and true fail before intent. No credential or provider operation occurred.

All **11 manifest artifact hashes** and **six adopted original report/probe files** verified byte-for-byte. The change contains only the CLI mapping, its regression tests and evidence; the prior authority state-machine review remains applicable. Original criterion text and all six pending states are unchanged. No database/web cutover, full-gate or stage-exit credit is granted.
