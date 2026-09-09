# Original TT02 deterministic replay

The exact original July 2026 no-activity RF case was regenerated successfully using the current canonical backend public parser and renderer. This independently verifies the A1 original-payload equivalence component; it does not certify the full #151 migration exit or a new provider acceptance.

The executed, redacted [JSON receipt](tt02-deterministic-replay.json) binds the exact original case, both output documents and all canonical backend files imported by the replay. The tested checkout HEAD is `3e8bf5187d614a3a2d02437f12186d90dbd19078`; the working-tree file hashes in the receipt identify the implementation actually executed. The original accepted authority evidence remains [the July14 receipt](../../../../docs/filing/evidence/rf1086-tt02-2026-07-14.json).

| Evidence | SHA-256 |
| --- | --- |
| Original complete case | `d73a5c57ff0cf971c7443423c58011b6e50a75997cea14ec3310bc49f04bd6f9` |
| Main XML | `37113adf3281a9c3b6b2564006f54f9925d1427b8592d7a9ed219d065b400e78` |
| Single child XML | `02ae217c54e8bf7313aa108223d4fe559242a8e47b95e5e4d8c22be55dd39556` |

Verification used one existing case, parsed unchanged through `parse_rf1086_case`. Assertions required income year 2025, zero activity events, one shareholder snapshot and exactly the original single child identity. `assess_rf1086_readiness` returned ready. `generate_rf1086_documents` produced both documents, and a repeated invocation returned identical bytes. Each document was compared byte for byte against both the historical `xml/` and `preflight-xml/` copy, then checked with `/usr/bin/xmllint --nonet --noout --schema` against the canonical bundled schema. Every comparison and both schema checks passed. The original source files' hashes were checked again after execution.

Only a private mode0700 temporary directory held the generated XML and schema copies, each mode0600. The complete case, identifiers, contact fields and raw XML are not copied into repository evidence. The replay used no provider-capable harness, provider adapter, credential, database or authority call; a Python audit hook rejected socket/network attempts and xmllint used `--nonet`. The durable [offline verifier](../../../../scripts/verify-rf1086-historical-replay.py) is identified by repository path and SHA-256 in the receipt. It takes explicit paths and contains no private case paths or shareholder identifiers. It hash-checks the case and both pairs of historical XML before parsing the case, refuses an existing output directory, and reports only fixed sanitized failure codes. Six executed negative checks cover wrong case hash, wrong XML hash, wrong child count, wrong preflight extent, XML hash verification before case parsing, and output overwrite refusal. These are opt-in verification checks; no mandatory gate depends on the private original fixture.

Repeat with the same original local source files and a new output directory, using the backend environment and the original expected case digest:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/backend/src \
  apps/backend/.venv/bin/python scripts/verify-rf1086-historical-replay.py \
  --case "$RF_CASE_PATH" \
  --expected-case-sha256 d73a5c57ff0cf971c7443423c58011b6e50a75997cea14ec3310bc49f04bd6f9 \
  --historical-evidence docs/filing/evidence/rf1086-tt02-2026-07-14.json \
  --xml-directory "$RF_XML_DIRECTORY" \
  --preflight-xml-directory "$RF_PREFLIGHT_XML_DIRECTORY" \
  --output-directory "$RF_NEW_PRIVATE_OUTPUT_DIRECTORY"
```

The verifier writes `receipt.json` and private XML/schema files to that new directory. Review only the redacted receipt for repository evidence. Do not substitute a reconstructed or different synthetic case.

This result resolves the missing exact-source availability documented in [the earlier search inventory](tt02-replay-availability.md). It does not replace the original historical authority receipt, rewrite provider references, activate production, or waive the remaining lifecycle/browser/review/two-pass/protected-integration requirements.
