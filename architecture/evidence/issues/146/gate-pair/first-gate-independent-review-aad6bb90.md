# Independent first-gate verification: aad6bb90

**PASS: all11 checks in the first committed immutable customer-ready gate.** Tested revision `aad6bb90951120b09771a23f58d5b662713e7a5a`; receipt and transcript first added in `50f969c04f4eabbe17ee2fcee36ac652d5ddcc05`.

Verified the committed schema with AJV2020/date-time validation; all11 unique commands against the tested producer and transcript; every exit0 and exact duration; start/end identity; sorted-key canonical JSON digest; transcript/producer hashes from committed bytes; ancestry and first-storage commit. Gate ran19:24:58.373–19:46:10.454UTC on2026-09-13 (1,272,081ms). Storage delta contains only24 evidence files/metadata; product source is unchanged.

- Canonical receipt: `159a7a200f226e857778508abb47d7f45d9a0bfaee30b5c393a2bf457c0fe7b6`
- Transcript: `30382a344a3b6d5441f74189b97fa795a81dfd6d3c28a5669cb4530490d038df`
- Tested producer: `0528b969d8d715a8276aa93beb0d30dc2879c5ee270ce7726fcd2e152cd3253c`

Actual Tax database execution passed22 lifecycle/API plus3 restricted-connection tests; RF/Authority database passed130. All six browser lanes passed with zero skips: public acquisition1, predecessor owner/cleanup/onboarding24, annual owner1, Authority11, freshRF12, Tax1. Those lane counts include their supporting guard tests. Twenty final-acceptance artifacts match both manifest digests and private originals, including the closed deployment-proof gap and source bindings. Original six criterion texts are unchanged.

Disclosures: broad backend2864passed,2pre-existing optional skips,854deselected; the optional validation-observation Python test skipped again in its dedicated lane because its database environment variable was absent, while the mandatory Node SQL test passed. Advisors report0blocking security/error findings and60performance warnings.

No gate/database/browser rerun. The running second gate, pair acceptance, protected/exact-main integration and full Company Tax/#152 exit remain unaccepted. Detailed commands, durations, line references and storage paths are in the JSON companion.
