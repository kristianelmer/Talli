# RF streaming archive format

Authenticated endpoint: `GET /api/v1/shareholder-register-filings/archive-source/production-stream?companyId=<uuid>&incomeYear=<year>`.
The generated client's `rf1086DownloadProductionArchive` returns an unconsumed
`Response`; save its body directly to a private `.ndjson` file. Do not buffer it
through `json()` or treat receiving HTTP 200 as a completed archive. Owner browser
download integration remains separate work.

Verify a saved download with the backend Python environment:

```sh
python apps/backend/scripts/verify_rf1086_archive.py archive.ndjson \
  --stream --company-id COMPANY_UUID --income-year 2025 \
  --require-source-history --require-feedback-originals
```

Every record is a UTF-8 JSON object followed by LF, with duplicate keys rejected.
Records appear in this exact order:

1. `codec: rf1086-production-stream-v1` and `canonicalArchive`: the existing
   byte-preserving RF canonical record. Maximum encoded line: 256 MiB; the
   canonical codec retains its own 64 MiB bound.
2. A `kind: sourceOriginal` record for every distinct captured document version,
   sorted by document ID, source year, metadata digest and content digest. Its
   `original` object has the same identity fields and `canonicalOriginal` as the
   existing inline source-original representation.
3. A `kind: feedbackOriginal` record for each bound feedback original, sorted by
   document ID, using that same envelope. RF's exact receipt binding and original
   submission attribution must also match. Unbound legacy artifacts are not
   silently substituted with current bucket contents.
4. A `kind: complete` record containing integer `sourceOriginals` and
   `feedbackOriginals` counts, plus lowercase `sha256` of all preceding **literal
   bytes including LF**. EOF must follow immediately.

Original-record lines are capped at 32 MiB; Documents still caps each serialized
original at 16 MiB. Combined source and feedback content is capped at 1 GiB. The
stream keeps the canonical archive and query identities in memory but fetches,
verifies and emits original contents one at a time. The verifier likewise discards
each verified original. The 128 MiB inline endpoint is unchanged.

Authentication and canonical validation precede HTTP streaming. Documents checks
current ownership and AAL2 for each retained-original read. Any failed read or
interruption prevents the terminal record; discard incomplete downloads. Do not
concatenate retries or append a new response to a partial file. Each retry is an
independent read of an archive snapshot.

The terminal checksum is a transfer-integrity commitment, **not an authenticated
signature**. The verifier checks internal evidence consistency and expected
company/year, performs no writes, and claims no database/object restoration or
provider acceptance. Strict feedback completeness rejects historical artifacts
without retained-original bindings. Local validation uses synthetic fixtures and
scaled size limits; full-size load and authenticated browser acceptance remain.
