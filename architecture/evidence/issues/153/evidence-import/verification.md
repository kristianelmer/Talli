# Accounts TT02 evidence projection

The canonical pure importer preserves all 43 frozen predecessor outputs and ordered
failures. Imported evidence stays pending. Identity authorization, database writes,
Audit continuation, provider-state ownership and web cutover remain pending.

The input copies nested data and requires the workflow to supply recording time.
The existing web wrapper remains authoritative and still supplies the clock.

The standalone date capture contains 1,804 finite Date.parse cases. The first
public importer test run had one fixture mismatch: the importer first trims
ECMAScript whitespace, unlike raw Date.parse. The corrected producer invokes the
unchanged released importer directly, capturing exact acceptance and rejection
messages for all 1,804 inputs plus 4,320 TimeClip boundary cases in six timezones.
All 2,112 parametrized tests pass, including all prior 258 Accounts pure tests.
The six timezone tests each execute 720 frozen boundary inputs.

The local date parser is adapted from pinned V8 source under its included BSD
license. Existing PyICU supplies timezone offsets at TimeClip endpoints because
macOS libc rejects negative civil years that V8 accepts. No new dependency or
provider operation is introduced. The earlier date comparison logs preserve the
original two libc early-year failures and intermediate correction; the final
public importer test log verifies the ICU implementation.

Both independent reviews of e412ebcc passed, resolving the offline ownership and
pure numeric/deep-metadata findings. Those exact reports are adopted here without
rewriting the previous phase's manifest. This is not a #153 stage-exit receipt;
all six original acceptance criteria remain pending.
