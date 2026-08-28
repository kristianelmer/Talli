# Public acquisition web feature

<!-- architecture-inventory
{"apiOperations":[],"dependencies":[],"publicEntryPoints":["@/features/public-acquisition","apps/web/features/public-acquisition","apps/web/features/public-acquisition/index.ts","apps/web/features/public-acquisition/PublicPage"],"routes":["/","/passer-talli","/pris","/hjelp","/sikkerhet","/status","/api/marketing-events"]}
-->

## Purpose

This feature owns the public recruitment homepage, public information
presentation, deny-by-default acquisition runtime projection, consent UI, and
privacy-minimized event vocabulary. It states the approved annual offer and
links each promoted capability to the versioned company-year boundary while the
product remains explicitly in free recruitment and validation mode.

## Boundary

The feature contains no eligibility policy, billing policy, provider call,
analytics persistence, or launch-clearance decision. `/sjekk-selskapet` remains
owned by `web:company-access`; billing owns any future checkout command. The
public feature may present shells and consume explicit technical runtime facts,
but cannot reimplement either policy. Measurement persistence is a
backend-system technical seam with a strict allowlist and no business data.
Missing or stale runtime clearance always means no checkout, no live-production
claim, and no paid acquisition.

## Tests

The feature tests prove the exact offer, sole primary eligibility action,
deny-by-default runtime and stop rules, approved rendered order, indexable route
inventory, privacy-safe measurement vocabulary, and exact agreement between the
public company-year promise and the company-access capability manifest.
