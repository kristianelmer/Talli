# Accounts response preservation and readiness preview

Standards review of af5c6523 identified STD-153-READ-1: an immutable valid
workspace containing 600-level JSON metadata passed row/model validation but
Pydantic failed after endpoint return, producing an internal 500. The original
probe and traceback are adopted unchanged. Accounts preview/workspace routes
still construct and validate their typed wire models, then use iterative JSON
encoding to preserve opaque metadata without the serializer depth limit.
Detaching immutable mappings is iterative too. Tests cover both routes at depths
1, 600 and 1200, complete metadata retention, ordinary Pydantic-compatible aliases,
UUID/timestamp/scalar formatting, and explicit cycle rejection. The original
reviewer probe now returns 200 for both shallow and 600-level responses.

The additive Accounts readiness-preview endpoint calls the already owned Python
rules with immutable Annual/Ledger facts and Corporate blockers. It preserves
all 11 frozen legacy ordered readiness cases, including disabled/enabled Corporate
checks and accepted/unaccepted manual warnings. It grants no durable permission
and adds no production operation. The generated client exposes the endpoint.
The initial route incorrectly supplied a fourth positional source argument;
its failed test log is retained and the route now uses explicit named fields.

All 81 focused Python tests pass, and architecture enforcement passes. The web
transport/presentation scaffold is being prepared separately and is excluded
from this bounded commit. Web caller cutover, positive source handoff, physical
contract/rollback and full #153 exit remain pending. Original af5c6523 Spec review
is still running and will be adopted when finalized. This is not full-stage credit.
