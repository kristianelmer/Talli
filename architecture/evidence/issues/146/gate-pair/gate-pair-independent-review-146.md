# Independent #146 local gate-pair review

**PASS: two linked complete local gates,11/11 each. Second receipt storage and final committed-byte reread remain pending.**

| Tested revision | Canonical evidence digest | Storage revision |
|---|---|---|
| `aad6bb90951120b09771a23f58d5b662713e7a5a` | `159a7a200f226e857778508abb47d7f45d9a0bfaee30b5c393a2bf457c0fe7b6` | `50f969c04f4eabbe17ee2fcee36ac652d5ddcc05` |
| `50f969c04f4eabbe17ee2fcee36ac652d5ddcc05` | `550416dc1164597cb6716bf4ecf7955db7241ae606e2e0d3fc7e4cdf37778533` | Not yet committed |

Independently validated both receipts against the committed schema with AJV2020/date-time checks; derived expected commands from each tested producer; matched all11 commands, exits and durations against raw transcripts; recomputed sorted-key canonical, transcript and producer hashes; checked start/end identity and summed elapsed times. First gate ended19:46:10.454UTC; second explicitly links it and started19:46:57.430UTC, ending20:08:04.858UTC on2026-09-13. Distinct revisions have the required Git ancestry and identical source outside evidence. Current untracked changes are the second receipt/transcript and gate-pair evidence.

Each gate actually ran22 Tax lifecycle/API plus3 restricted-runtime tests with no skips. All six browser lanes passed with zero skips: public acquisition1; predecessor owner/cleanup/onboarding24; annual owner1; Authority11; freshRF12; Tax1. The second local gate completed both the RF journey and subsequent Tax journey.

Both runs disclose2864 backend passes,2existing optional skips and854deselections. Validation-observation’s optional Python adapter test skipped again in its dedicated lane because its database variable was absent; mandatory Node SQL observation coverage passed. Advisors report0blocking security/error findings and60performance warnings.

CI50f attempt1 remains a historical failed required RF browser journey. The unchanged retry was not inspected, and neither its success nor a synchronization cause is inferred. Local passing evidence does not erase that failure or grant protected integration acceptance.

No gate/database/browser rerun. Commit the exact second receipt/transcript and reread committed bytes before final pair acceptance. Protected merge/exact-main Release/Preview and full Company Tax/#152 exit remain unaccepted. The JSON companion includes full check arrays, timestamps, source scope and lane line references.
