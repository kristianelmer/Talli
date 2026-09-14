# Publication and final documentation follow-up

53b3ae3e full gate failed at credential scanning because a retained pytest collection failure printed synthetic PEM headers in test identifiers. The published rehearsal-tail-second log now redacts only those header bytes; its manifest explicitly records the exact original SHA, private path and published transformation. The original remains unchanged privately and at commit 53b3ae3e. The scanner is unchanged. The failed full gate transcript is published as an explicitly redacted derivative, never canonical passing evidence.

Added a genuine expired-TOTP timestamp control alongside the existing AAL1 control, closing STD-153-DEPENDENCY-1. All three Support scope cases pass with both controls, actual grant/open/read/revoke and rollback cleanup. The original Standards finding is adopted unchanged. Updated Accounts module prose to describe its implemented cutover, rollback, generated web boundary and durable source coverage. Full stage exit and protected integration remain pending.

Credential checks and architecture validation pass. No provider/hosted/production action.
