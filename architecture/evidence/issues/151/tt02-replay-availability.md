# Historical RF-1086 TT02 replay availability

**Resolved: exact historical payload regeneration passed offline.** The recovered original complete case produces both original TT02 XML documents byte for byte through the canonical RF backend implementation. See [the redacted replay receipt](tt02-deterministic-replay.json) and [its scope and procedure](tt02-deterministic-replay.md). This is A1 replay evidence, not a new authority run or the full #151 exit.

The search inventory below was adopted at immutable entry baseline `91b178c281bcc5fb887a6257d2f72e380199f3e6` on 9 September 2026. It records why the input was initially unavailable; the later recovery and executed comparison supersede that blocker. Source references in the historical inventory are repository-relative at that baseline unless explicitly historical.

## Recovery and executed result

A bounded lookup of the exact archived RF task revealed a concrete historical checkout and its ignored authority-test output directory. The original complete case SHA-256 is `d73a5c57ff0cf971c7443423c58011b6e50a75997cea14ec3310bc49f04bd6f9`. Both the generated `xml/` and `preflight-xml/` copies matched the already recorded main and child hashes before replay.

The canonical public parser and generator then read that single unchanged original case into a private temporary directory. The replay asserted 2025, no activity events, one shareholder and one child document; readiness was ready. Both generated documents matched both historical copies byte for byte, and a repeated generation returned identical bytes. Both bundled XSD validations passed. The receipt records exact input/output/source-code hashes, the durable verifier path/hash and runtime version without the case, XML, personal identifier or contact data. The verifier is `scripts/verify-rf1086-historical-replay.py`; its paths are explicit CLI arguments and the original hashes are checked before parsing.

The original files were read only. Output directories are mode0700 and generated documents/schemas mode0600. No provider-capable harness, authority adapter, credential, database, network call or production activation was used. The private source remains local; the checked-in receipt contains redacted proof only.

## Evidence retained

- `docs/filing/evidence/rf1086-tt02-2026-07-14.json`, introduced by `22225615`, records the original code `1d06b06`, 2025 no-activity shape, one shareholder subdocument, successful test submission, matching archived-document hashes, UUID idempotency keys and provider references.
- Exact recorded main XML SHA-256: `37113adf3281a9c3b6b2564006f54f9925d1427b8592d7a9ed219d065b400e78`.
- Exact recorded child XML SHA-256: `02ae217c54e8bf7313aa108223d4fe559242a8e47b95e5e4d8c22be55dd39556`.
- The companion Markdown explicitly says raw XML and the synthetic personal identifier are excluded. It says an ignored local resumable evidence journal existed, but gives no actual filesystem path. The July14 section in `docs/filing/authority-onboarding-runbook.md:630–650` likewise links only the sanitized pair.
- `tests/rf1086_tt02_evidence.test.mjs` verifies the existing acceptance/reference/hash bookkeeping. It neither regenerates the payload nor supplies the missing fixture.

## Historical search boundaries and initial result

1. Searched repository RF evidence, fixtures, runbooks, source CLI environment-path references and committed redacted evidence links for the two exact hashes, named RF case/journal paths and the accepted synthetic company reference. Found no complete exact TT02 input or raw XML.
2. Inspected the original authority harness with `git show 1d06b06:scripts/rf1086-authority-test.mjs`. It requires the caller-supplied `TALLI_RF1086_CASE_PATH` and `TALLI_RF1086_EVIDENCE_PATH`, writes raw generated files under `<dirname(evidencePath)>/xml/1086H.xml` and `1086U-*.xml`, and stores the resolved `evidencePath` inside the resumable journal. Neither actual environment path is present in the public sanitized receipt, `.env.example`, or matching documentation history.
3. Inspected the current relocated `apps/backend/src/talli_backend/authority_tools/rf1086_test.py`; it preserves the same caller-supplied case/journal paths and sibling `xml/` directory. No provider-capable CLI was executed.
4. Followed only the concrete generic runbook paths: `case.json`, `preview.json`, `out/1086H.xml`, `out/rf1086/1086H.xml` and `out/rf1086/`. All are absent in both known repository roots: the active Codex worktree and `/Users/kristianelmer/Documents/Holding accounting`. Both roots have no `out/` directory. `.gitignore` excludes `out/`.
5. Inspected local Git history filenames for RF/TT02 cases and raw XML, including the original generator revision. No raw `.xml` file has been tracked in the searched local history. The RF fixture set consists of the existing five synthetic generator fixtures and two invalid fixtures; no separately named original Tenor/TT02 RF case is tracked.
6. Checked the explicitly related #81 issue body and its six comments for a concrete case/journal/archive filesystem reference. No such reference was found. This was metadata reading only; no authority or unrelated personal archive was searched.

The `no_activity.json` fixture at both original generator revision `1d06b06` and current main has a different company identity from the recorded TT02 run. Therefore replaying that fixture is useful migration characterization but cannot establish either original TT02 document hash. Other test fixtures for the same synthetic company concern tax/accounts or corporate documents and are not the RF request source; combining them would invent the missing input.

## Former missing-input condition (now resolved)

The initial audit required the original complete RF case JSON (including exact company/contact/address/shareholder/snapshot values), **or** the exact two submitted/archived XML files. Both were subsequently found and the complete case was replayed as recorded above. The ignored resumable RF journal may locate the original directory through its `evidencePath`; sibling `xml/` files would then be hashable entirely offline. A journal containing only hashes and references does not recover missing XML preimages.

With an exact existing file path supplied, first hash the files as bytes and compare both recorded digests, without printing XML or identifiers. If the original case is available, run only the deterministic local generator in an isolated temporary output directory and compare its bytes against these known digests; do not run the authority CLI merely because it supports accepted-journal continuation. Preserve the original fixture/archive unchanged and attribute any copied local golden as historical only after the hashes match.

Before recovery, the truthful A1 status was that historical accepted TT02 evidence existed but **exact regeneration had not yet been demonstrated**. The executed replay receipt now closes that specific gap. Do not fabricate a reconstructed fixture, claim a hash match without executing it, replace these hashes, call synthetic migration goldens authority acceptance, or silently waive A1. This finding does not authorize live provider archive retrieval, credential use or a new provider test.

## Earlier bounded app index lookup

The app task index was checked at its maximum allowed `limit:50` (a request for200 was rejected by the API), including pinned tasks. Filtering only project `local-2c5db555755831311cd05b974f11a8b4` yielded five current cancellation/September oversight tasks and no precise RF/TT02/Maskinporten rehearsal title or summary. No July14 RF task was identified, so no unrelated or broad task history was read and no task was messaged. This index window does not prove the historical task was deleted; it only failed to locate an exact case/journal path within the authorized bounded lookup.
