# Synthetic operator STOP browser verification

Passed 43 assertions covering 16 distinct checks. Desktop 1440 × 1100 and mobile 375 × 812 screenshots were visually inspected. Both mobile states checked for horizontal overflow passed.

The temporary Next fixture imports the shipped AnnualBillingSupport component, AnnualSupportCleanupRecoveryControl, and recoverAnnualSupportCleanup server action. The action uses the generated transport and calls the actual FastAPI STOP recovery route/public service over loopback HTTP. Authentication, opened-case persistence and provider reconciliation are synthetic fixtures. No shared database, hosted service, real customer, MT or external provider was used. This does not verify the production operator dashboard loader/session/database seams.

Verified unknown and pending remain unconfirmed; confirmed results preserve the original STOP and receipt; confirmed replay makes another scoped HTTP request without another provider read; financial balances stay unchanged; native history links retain company, opened case and purchase cursor without a fragment. Closing the fixture case causes 403 before provider read and server-action invalidation removes purchase evidence. Session loss stops before backend requests and keeps the return scope on the sign-in link.

Published artifacts: verification-result.json and artifacts/*.png. The harness scripts and build log are retained in the local private evidence archive. The only observed console error was the fixture favicon 404.
