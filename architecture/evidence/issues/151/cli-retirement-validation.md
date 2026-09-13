# RF canonical owner and retained CLI validation — 2026-09-09

Scope: local implementation checkpoint for #151, within the serial #192 route. No stage-exit, provider, TT02, protected-main, or production acceptance is claimed.

## Source and boundary

Pinned original source: `91b178c281bcc5fb887a6257d2f72e380199f3e6`. Original files and fixed synthetic/public outputs were captured in an isolated archive before retirement; artifact/source SHA-256 values are in `apps/backend/tests/fixtures/rf1086_oracle/manifest.json`.

The sole RF implementation now lives in `apps/backend/src/talli_backend/modules/shareholder_register_filing/`, behind `public.py`. It preserves the original offline parser/coercion, arbitrary identifiers, naive civil timestamps, float formatting, code evidence, XML and XSD bytes, readiness wording, independent confirmation timestamps, strict UTF-8 hashing, Python codepoint ordering, UUIDv5, and retained production journal/feedback semantics. Persisted preview/simulation uses the original deployed JavaScript behavior separately where the old implementations differed. No credentials or Pydantic models enter the public contracts.

The six retained commands in `holding_cli/main.py` now perform presentation/filesystem/XML-validator work around that public interface:

- `simulate-aksjonaerregister`
- `validate-rf1086-xml`
- `validate-case`
- `validate-public-data`
- `render-rf1086-preview`
- `simulate-rf1086-submission`

Removed only the five RF-only predecessor files: `holding_core/{models,readiness,rf1086,rf1086_codes,rf1086_submission}.py`. Removed their exports and RF-only report code from shared files. Root `holding_core/submission.py` and all unrelated annual/corporate/generic code remain. All seven retained annual validation definitions, both annual/corporate CLI function ASTs, and eight unrelated core source files match the pinned original exactly.

Root `pyproject.toml` declares `talli-backend==0.1.0` with the local `apps/backend` uv source; both distributions use the backend's existing Python `>=3.12,<3.14` boundary. `uv lock` and `uv sync --locked` pass. There is no backend import fallback into root `holding_core`.

## Focused evidence

- `apps/backend/.venv/bin/python -m pytest apps/backend/tests/test_rf1086_rule_equivalence.py apps/backend/tests/test_rf1086_preparation.py apps/backend/tests/test_rf1086_source_facts.py apps/backend/tests/test_shareholder_register_filing_contract.py apps/backend/tests/test_rf1086_offline_equivalence.py apps/backend/tests/test_rf1086_cli_equivalence.py -q`: **149 passed**, 4.82 s, 0 skipped.
- Provider/production/API regression (`test_rf1086_authority.py`, `test_shareholder_register_filing_production.py`, `test_legacy_rf1086_api.py`): **287 passed**, 5.70 s, 0 skipped. Subsequent changes only extend source-evidence DTOs/tests, not these production contracts.
- `uv run --locked python -m unittest discover -s tests -p 'test_*.py'`: **55 passed**, 3.102 s, including all 12 retargeted original RF cases and unchanged annual/corporate/generic suites.
- Actual installed `.venv/bin/talli` from a temporary directory outside the checkout, with no `PYTHONPATH`: **12 checks passed**, spanning all six commands, blocked/invalid output and actual-clock simulation.
- `uv build --project apps/backend --wheel --out-dir /tmp/talli-151-backend-package`: passed. Both bundled XSD bytes match pinned source hashes; the wheel contains no `holding_core` implementation.
- `git diff --check`: passed at source-ready observation.

The new source-evidence cases preserve complete raw opening/journal enumeration independently from renderability: invalid rendering yields unavailable readiness without dropping retained history. The current digest includes raw opening identities/counts/digests, every journal attempt/resulting status, all retained rows and migration attestation. Missing/truncated/quarantined/stale evidence fails closed; no outside-Talli negative history or provider attribution is inferred.

## Retired wrapper-test disposition

`tests/test_rf1086.py` retains its 12 original behavior checks using canonical public values. `tests/test_rf1086_submission.py` contained six tests of the now-deleted, unbound wrapper:

- Paid-flag preparation/security-review gates are superseded by the actual authenticated canonical workflow gates (`test_authenticated_send_preserves_gate_order_token_before_begin_and_finally_discard`, `test_send_failures_stop_at_expected_gate_and_release_resources`, and actual API/database coverage owned by B/C). No fake paid flags are added to the RF domain.
- Formation/code allowance and excluded sale/dividend evidence remain characterized by `test_original_code_evidence_preserved_without_expanding_live_scope` and retained root RF code tests. The old wrapper's formation-production claim is not transferred into the supported no-activity release path.
- Authority/preview confirmations, per-operation idempotency, original hashes, feedback and retry behavior remain covered by the offline oracle, `test_exact_persisted_simulation_and_payload_identity`, `test_journal_saves_original_hashes_and_per_operation_uuid_and_replay_reuses_success_without_io`, `test_failed_retry_uses_persisted_key_and_attempt_twenty_blocks`, and feedback/receipt persistence cases.

The six obsolete wrapper tests are retired with their implementation; unrelated generic submission/billing tests remain and pass.

## Exact runtime limit

The pinned original source was first evaluated in the existing backend Python 3.12.11/Pydantic 2.11.7 runtime, identical to the canonical implementation. All 15 captured CLI subprocess cases match in that runtime. A second capture uses the original root lock's Pydantic 2.13.4: **13/15 match byte-for-byte**, with the remaining two (`render_invalid`, `generate_invalid`) differing only in `https://errors.pydantic.dev/2.13/` versus `/2.11/`. All diagnostics otherwise, output categories, results and exit codes match. `locked-runtime-comparison.json` and its manifest hash preserve this distinction. The CLI truthfully reports the actual parser documentation version; no exception-text compatibility rewrite is used.

Historical TT02 inputs/authority evidence, integrated real database/browser verification and the required complete stage gates remain separately owned/pending. This report does not claim them.
