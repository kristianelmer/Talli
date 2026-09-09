# Historical RF-1086 TT02 replay availability

Entry inventory adopted on 9 September 2026 at immutable baseline `91b178c281bcc5fb887a6257d2f72e380199f3e6`. #150 is closed with protected integration; #151 entry evidence is being recorded. No #151 implementation or exit is claimed here. Source references are repository-relative at this baseline unless explicitly historical.

## Evidence retained

- `docs/filing/evidence/rf1086-tt02-2026-07-14.json`, introduced by `22225615`, records the original code `1d06b06`, 2025 no-activity shape, one shareholder subdocument, successful test submission, matching archived-document hashes, UUID idempotency keys and provider references.
- Exact recorded main XML SHA-256: `37113adf3281a9c3b6b2564006f54f9925d1427b8592d7a9ed219d065b400e78`.
- Exact recorded child XML SHA-256: `02ae217c54e8bf7313aa108223d4fe559242a8e47b95e5e4d8c22be55dd39556`.
- The companion Markdown explicitly says raw XML and the synthetic personal identifier are excluded. It says an ignored local resumable evidence journal existed, but gives no actual filesystem path. The July14 section in `docs/filing/authority-onboarding-runbook.md:630–650` likewise links only the sanitized pair.
- `tests/rf1086_tt02_evidence.test.mjs` verifies the existing acceptance/reference/hash bookkeeping. It neither regenerates the payload nor supplies the missing fixture.

## Search boundaries and result

1. Searched repository RF evidence, fixtures, runbooks, source CLI environment-path references and committed redacted evidence links for the two exact hashes, named RF case/journal paths and the accepted synthetic company reference. Found no complete exact TT02 input or raw XML.
2. Inspected the original authority harness with `git show 1d06b06:scripts/rf1086-authority-test.mjs`. It requires the caller-supplied `TALLI_RF1086_CASE_PATH` and `TALLI_RF1086_EVIDENCE_PATH`, writes raw generated files under `<dirname(evidencePath)>/xml/1086H.xml` and `1086U-*.xml`, and stores the resolved `evidencePath` inside the resumable journal. Neither actual environment path is present in the public sanitized receipt, `.env.example`, or matching documentation history.
3. Inspected the current relocated `apps/backend/src/talli_backend/authority_tools/rf1086_test.py`; it preserves the same caller-supplied case/journal paths and sibling `xml/` directory. No provider-capable CLI was executed.
4. Followed only the concrete generic runbook paths: `case.json`, `preview.json`, `out/1086H.xml`, `out/rf1086/1086H.xml` and `out/rf1086/`. All are absent in both known repository roots: the active Codex worktree and `/Users/kristianelmer/Documents/Holding accounting`. Both roots have no `out/` directory. `.gitignore` excludes `out/`.
5. Inspected local Git history filenames for RF/TT02 cases and raw XML, including the original generator revision. No raw `.xml` file has been tracked in the searched local history. The RF fixture set consists of the existing five synthetic generator fixtures and two invalid fixtures; no separately named original Tenor/TT02 RF case is tracked.
6. Checked the explicitly related #81 issue body and its six comments for a concrete case/journal/archive filesystem reference. No such reference was found. This was metadata reading only; no authority or unrelated personal archive was searched.

The `no_activity.json` fixture at both original generator revision `1d06b06` and current main has a different company identity from the recorded TT02 run. Therefore replaying that fixture is useful migration characterization but cannot establish either original TT02 document hash. Other test fixtures for the same synthetic company concern tax/accounts or corporate documents and are not the RF request source; combining them would invent the missing input.

## What is missing and what would resolve it

The original complete RF case JSON (including exact company/contact/address/shareholder/snapshot values), **or** the exact two submitted/archived XML files, is needed. The ignored resumable RF journal may locate the original directory through its `evidencePath`; sibling `xml/` files would then be hashable entirely offline. A journal containing only hashes and references does not recover missing XML preimages.

With an exact existing file path supplied, first hash the files as bytes and compare both recorded digests, without printing XML or identifiers. If the original case is available, run only the deterministic local generator in an isolated temporary output directory and compare its bytes against these known digests; do not run the authority CLI merely because it supports accepted-journal continuation. Preserve the original fixture/archive unchanged and attribute any copied local golden as historical only after the hashes match.

Until that material is located, state A1 evidence precisely: historical accepted TT02 evidence exists and current migration can be compared with pinned existing synthetic generator outputs; **exact regeneration of the historical accepted no-activity payload has not been demonstrated**. Do not fabricate a reconstructed fixture, claim a hash match without executing it, replace these hashes, call synthetic migration goldens authority acceptance, or silently waive A1. This finding does not authorize live provider archive retrieval, credential use or a new provider test.

## Additional bounded app index lookup

The app task index was checked at its maximum allowed `limit:50` (a request for200 was rejected by the API), including pinned tasks. Filtering only project `local-2c5db555755831311cd05b974f11a8b4` yielded five current cancellation/September oversight tasks and no precise RF/TT02/Maskinporten rehearsal title or summary. No July14 RF task was identified, so no unrelated or broad task history was read and no task was messaged. This index window does not prove the historical task was deleted; it only failed to locate an exact case/journal path within the authorized bounded lookup.
