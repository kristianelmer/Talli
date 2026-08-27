# Public acquisition web feature

<!-- architecture-inventory
{"apiOperations":[],"dependencies":[],"publicEntryPoints":["@/features/public-acquisition","apps/web/features/public-acquisition","apps/web/features/public-acquisition/index.ts"],"routes":["/"]}
-->

## Purpose

This feature owns the public recruitment homepage presentation. It states the
approved annual offer and links each promoted capability to the versioned
company-year boundary while the product remains explicitly in free recruitment
and validation mode.

## Boundary

The feature contains no eligibility policy, checkout, provider call, analytics
persistence, or launch-clearance decision. `/sjekk-selskapet` remains owned by
`web:company-access`. The homepage may link to that public contract but cannot
reimplement it. Missing future runtime clearance must continue to mean no
checkout and no live-production claim.

## Tests

The feature test proves the exact offer, the sole primary eligibility action,
the deny-by-default recruitment state, the approved rendered homepage order, and
exact agreement between the complete public company-year promise and the
committed company-access capability manifest.
