# RF web rule retirement and receiver checks

Implementation checkpoint, 9 September 2026. This is a coverage map, not a #151
exit result. The original source is protected-main
`91b178c281bcc5fb887a6257d2f72e380199f3e6`.

The original renderer, simulation and approval outputs were captured before
their implementations were removed. Canonical tests compare fixed synthetic
outputs with the one backend implementation. They do not execute a second
production implementation or establish historical TT02 regeneration.

| Retired test or rule | Preserved intent and current coverage |
| --- | --- |
| `tests/rf1086_persisted_preview.test.mjs` | Opening identities, shareholder totals, defaults, ready/blocked output and exact original XML/text are checked by `test_rf1086_rule_equivalence.py` and `test_rf1086_preparation.py`. The web no longer has a local renderer or a Python subprocess bridge. |
| `tests/rf1086_submission_persisted.test.mjs` | Real confirmations, deterministic request hashes/keys, receipt fields, structured feedback and submitted payload identity are checked by `test_rf1086_preparation.py` and `test_rf1086_offline_equivalence.py`. The six retained CLI commands have actual subprocess checks in `test_rf1086_cli_equivalence.py`. The former standalone web production adapter is retired; the authenticated production workflow remains subject to its original gates. |
| `tests/production_approval.test.mjs` and `apps/web/app/lib/production-approval.ts` | Canonical approval fields/order/hash are checked against pinned original vectors in `test_shareholder_register_filing_production.py`; modified/incomplete manifests fail before token acquisition or provider effects. `test_rf1086_preparation.py` checks the original Norwegian payload label and verified approving actor. The fresh-renderer-to-real-SQL approval rehearsal is separate database evidence. |
| Three duplicate rule tests in `tests/production_submission.test.mjs` and `apps/web/app/lib/production-submission.ts` | Actual journal transitions, unknown effects, terminal recovery and explicit persisted authority feedback are checked by `test_shareholder_register_filing_production.py` and the database suite. The unbound TypeScript transition helper is removed. The file retains all three web recovery, Documents lifecycle and polling-presentation checks. |
| RF section of `tests/investments_cross_output_reconciliation.test.mjs` | The existing issuer-only source facts now run through the canonical RF public renderer using a test-only subprocess adapter. XML remains unchanged across investment activity, which is not issuer shareholder data. All tax, accounts, Ledger, archive and correction assertions remain. |
| `tests/controlled_production_beta_actions.test.mjs` | Approval carries local UUID identities and the real-filing acknowledgement through authenticated generated transport. Payload and MFA enforcement are verified at the actual backend boundary. A failed production-history read returns the existing error result; it cannot masquerade as a healthy empty history. Unchanged owner, operator, System User and final-feedback presentation checks remain. |
| `tests/documents.test.mjs` | The RF producer relationship is checked at the canonical adapter; Documents retains metadata, private-object and integrity ownership. |

The existing `test:rf1086:persisted`, `test:rf1086:submission` and
`test:rf1086:production-pilot` commands now run those canonical suites. The
boundary web lane also runs the generated RF transport tests and local browser
fixture guards. Neither fixture guards nor static source checks are a claim
that the full browser/database journey passed.

Focused root observations:

- Cross-output, retained production presentation and Documents: 10 passed,
  zero skipped (`/tmp/talli-151-cross-output-and-documents.log`).
- Owner action contracts and both RF fixture guard suites: 17 passed, zero
  skipped (`/tmp/talli-151-owner-action-contracts.log`).
- Generated RF transport: 11 passed at the integration checkpoint.

Database lifecycle, current-schema browser, sibling and archive equivalence,
the full immutable gates, protected integration and the original TT02 fixture
remain separately tracked requirements. The pending exact 15-tuple amendment
has not been applied to the registry or checker.
