# Historical protocol evidence layout

The [complete proof bundle](complete-proof.tar.gz) retains all original artifacts,
including the three executable reproduction files, byte for byte. Its SHA-256 is
`62112752307baa2e2aa8323fabf936085c0d923945fb72b13457b1318daeee1f`.
Extract it outside the repository before following the [reproduction instructions](README.md).
`artifact-sha256.json` describes the original bundle contents. The readable README,
results, manifests and transcript here are identical copies of those originals.
Historical executable files are retained in the archive rather than installed as
an ongoing temporary equivalence suite. `node24-repeat/` holds root's independent
repeat with the same harness and pinned Node24.20.0; its manifest binds identical
application sources and its transcript records29passing checks.
