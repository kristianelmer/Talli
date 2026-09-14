# Standards follow-up — missing workspace session

**PASS: the Spec-reported missing-token finding is closed; no new Standards finding.** Reviewed `f5a9f41f79ff54c5d2a4b9d58b8ab67d77419115...909bd28daea26f9eb130aeff7cf9ab8e86faab74`, six files. Uncommitted backend readiness work is excluded.

The source helper now accepts the nullable session boundary explicitly. A missing token with a nonempty company scope returns the existing unavailable result without attempting a query; an empty scope remains complete empty data. `loadWorkspaceData` always calls that helper and already includes `taxSource.error` in its returned error. This prevents the earlier successful-empty fallback for a requested authenticated scope and aligns with ADR0012’s fail-closed boundary. No domain policy or persistence responsibility moves into the web layer.

Independent isolated **Node24.20.0 verification passed all 18 source/consumer tests**, including nonempty/empty missing-token controls with zero calls and existing Archive/readiness failure behavior. Both committed artifact hashes match. The prior exact Archive/readiness bodies and compatibility checker are untouched.

This is bounded source and dependency-double verification. No browser, real authentication, API/database, cutover, full-stage or release-gate acceptance is claimed. Exact revisions, source hashes and transcript binding accompany this report.
