PASS — bounded Spec review; no actionable finding.

Reviewed `006469373fc79f16c20dfec75bbc0d3ecd51ff6c...5915af48277c4074556ba2b750c93e523ffeb85a` against #153’s physical retirement requirement and #132’s preservation/authorization envelope. The five non-evidence changes are confined to test fixtures and their tests; no application compatibility layer or Accounts-row authority is introduced.

The selector retains exactly six public projections while present. Their absence requires complete retirement, Accounts `contracted` state and six physical owned families. Partial retirement, contradictory contracted/public state, unexpected relation kinds and missing owned families reject before fixture effects. The existing finite-authority transaction implementation remains byte-identical, preserving its ACL, FORCE RLS, trigger and rollback checks.

Fresh RF cleanup retains company-scoped mirror deletion before canonical opening deletion when mirrors exist. Contracted cleanup omits absent tables. The original success/failure cleanup cases remain, with contracted cases added. Every assertion line in the actual fresh RF browser is unchanged; feedback business assertions are untouched.

Independently ran the two pinned fixture suites using Node 24.20.0: 30 passed, zero skipped. Twelve additional probes of the actual selector passed, including missing state, absent phase row, public/owned views, contradictory state and remote-host rejection. These use synthetic catalog responses, not SQL. The committed broader fixture transcript separately records 52 passed and one existing optional database skip.

Verified all 16 manifest artifact hashes/sizes and 11 adopted original role-creation review/probe files byte-for-byte. The original 006 gate transcript retains the missing-public-table RF failures and receives no complete-gate credit. The manifest honestly leaves dedicated real-runtime verification pending.

This pass covers the fixture correction only. It does not certify the pending runtime rerun, complete immutable gate pair, protected integration or #153 exit. No shared repository, database, Docker or provider state was changed.
