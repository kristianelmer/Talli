# Complete RF feedback archive scan — partial #193 work

The approved synthetic baseline and archive have been independently verified at
the earlier source revision recorded in archive-recovery-20260915.json. That live
receipt does not validate this subsequent pagination implementation.

A local red regression showed that final feedback on page two was ignored by a
single-page shape guard. The canonical RF owner now acquires every declared page
before classifying or persisting feedback. Every page must retain total count,
page count, requested page index and expected extent for size 50. Repeated entries
across pages and missing/changed pages fail closed. Only a complete collection may
produce a final decision; conflicting later feedback cannot be hidden by an early
accepted response. Reference-document fetches remain read-only and submitted XML
is filtered by exact hashes as before.

Per-scan operational bounds are 100 pages, 32 MiB of listed content and 32 MiB of
processed document bytes, and 60 seconds. Exceeding a capacity bound requires action;
timeout records unknown. These are defensive runtime limits, not a new supported
company boundary. Resumable acquisition for collections exceeding the scan budget,
the adapter's existing JSON response-size budget and complete supported-case/load
proof remain explicit RF completion work. No RF criterion is marked complete.

The public archive_reads value still counts reconciliation poll iterations, as it
already did for reference-document GETs. Page requests belong to one complete poll.
No mutation endpoint, approval contract, SQL schema, credential activation or other
filing owner changes. Tests use only synthetic read-only authorities.
