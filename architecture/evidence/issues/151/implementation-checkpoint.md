# RF migration implementation checkpoint

9 September 2026, following entry commit
`7a49f010229baf13d4942364d352786d7cddc5c3`. This records working-tree
implementation and focused verification. It is not either immutable final gate,
a database cutover completion, historical TT02 regeneration or a #151 closure.

RF case parsing, XML, readiness, confirmation, simulation, approval, production
journal/recovery and source evidence now use the canonical backend capability.
The shared CLI delegates its six existing RF commands to that public contract.
Five RF-only core files, the frozen production adapter/workflow, and duplicate
web renderer/approval/transition implementations have been retired. The remaining
web simulation bridge and mixed actions/readers await the exact scope amendment.

The two existing Send/recovery HTTP contracts are unchanged. The additive
workspace and preparation API uses verified actors, typed intent, no-store
responses and generated web transport. An independent review found and closed
a nested receipt timestamp-format regression: actual HTTP reads now preserve
the original JSON timestamps, including fractional precision.

The new-year workflow writes RF shareholder facts and the Ledger-owned original
bank input under the preserved snapshot UUID, together with the existing posting
and workflow receipt. The application read joins those owners. Archive source
composition removes its two opening-table reads and preserves every remaining
mixed query chain; all 27 original archive-input fields match in executed route
comparisons. The backup manifest names the new physical owners while retaining
uncut sibling relations and dependency order.

Focused checks passed:

- Backend boundary: 2,740 passed, two existing optional database skips, 764
  database cases excluded from this lane.
- Web boundary: 188 presentation/transport checks plus 13 fixture guards, no
  skips. The actual database/browser journey is separate.
- Launch rehearsal: all 59 command groups completed successfully. Its component
  suites overlap; their counts must not be summed as unique coverage. One
  optional official-XML-schema check skipped because its external schemas were
  not supplied in that test lane.
- Both production builds and both generated-contract drift checks passed.
- RF HTTP API after the timestamp correction: 94 passed, including all four
  original simulation oracle cases and zero/three/six fractional-digit forms.
- Physical backup catalog: nine existing checks passed after ownership updates.
- Canonical pure/source/CLI and installed-package checks are recorded in
  [cli-retirement-validation.md](cli-retirement-validation.md), including the
  precisely bounded Pydantic documentation-URL difference between original
  root-lock and backend runtimes.

Successful logs and SHA-256 values are in [focused/manifest.json](focused/manifest.json).
These checks ran on an evolving working tree and do not qualify as immutable
complete-gate evidence. Existing API shapes were compared with protected-main
in [openapi-existing-contract-comparison.json](openapi-existing-contract-comparison.json):
no existing schema or path changed; 26 schemas and ten paths were added.

The [SQL access review](sql-access-review.md) records its bounded source findings.
The [root integration review](root-integration-review.md) excludes its author's
own RF pure/CLI/archive work. The [archive comparison](archive-receiver-validation.json)
and [test retirement map](web-test-retirement-map.md) describe their exact scopes.

Still pending:

- Retained database apply, complete expand/cutover/contract and rollback/recutover
  proof, restricted-role and concurrency tests, and the final browser journey.
  An empty-fixture expand/cutover/contract/full rollback transaction rehearsal
  passed without retained database changes. The quarantined foreign-holder read,
  owner-only artifact policy and retained-event digest corrections are present;
  their final database proof remains with lifecycle work. The SQL access review
  also found reviewer preview-lock authorization, current support permission/test
  evidence, transitive preview quarantine and support-purpose filtering gaps.
  These and physical rebinding of predecessor ON CONFLICT routines remain open.
- Kristian's affirmative decision on the reviewed exact 15-tuple amendment.
  Neither the immutable baseline nor the pending checker exception has changed.
- The original 14 July TT02 input/XML, needed for exact historical regeneration.
  Current synthetic goldens do not replace it.
- Final registry/catalog/dependency evidence, independent full review, two
  immutable complete gates and protected integration.

The serialized source order and production freeze remain in force. No provider
test, filing, spending or production activation is claimed by this checkpoint.
