# #150 Maskinporten RS256 dependency note

Read-only observation: 2026-09-09T11:57:12.733567+00:00. Repository basis: `b30312de11ad942479421def243e4a2252fbf166`. No package installation, dependency resolution, tests, repository changes, credentials, or provider operations were performed.

Recommend one direct runtime dependency: **`cryptography==50.0.1`**, maintained by the Python Cryptographic Authority. PyPI identifies it as the latest stable release, published 25 August 2026; its Python requirement is `!=3.9.0,!=3.9.1,>=3.9`, covering the backend's `>=3.12,<3.14`. This is the minimal direct dependency for the existing fixed RS256 signing requirement: standard-library JSON/base64url framing plus the maintained RSA signing primitive. A separate JWT package adds no necessary capability to this bounded port. [PyPI release](https://pypi.org/project/cryptography/50.0.1/), [exact release metadata](https://pypi.org/pypi/cryptography/50.0.1/json).

## Compatibility and dependency footprint

The current machine reports `arm64`; Release CI uses Python 3.12 on `ubuntu-latest`. The package publishes non-yanked `cp311-abi3` wheels, explicitly labeled CPython 3.11+, including the following Python 3.12-compatible choices. The table records published artifacts, not an installation result. [Published files](https://pypi.org/project/cryptography/50.0.1/#files).

| Environment | Wheel filename | SHA-256 |
| --- | --- | --- |
| macOS 11+ ARM64 | `cryptography-50.0.1-cp311-abi3-macosx_11_0_arm64.whl` | `b8f852c65863251b9e3a1b8c150ce21e59b522dbb6a7d4bc80e680d38388e986` |
| Linux x86-64, glibc 2.17+ | `cryptography-50.0.1-cp311-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | `ff838d62ec1bfce4f9ba7fa16f4a7b554cd8d0c299e6be37502161a660c84eef` |
| Linux ARM64, glibc 2.17+ | `cryptography-50.0.1-cp311-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl` | `53e279950892dc102c6b4e52af03ae5ea92fac572a1ddab78ca73a997f62b69f` |

These wheels bundle OpenSSL; compatible wheel installation needs no Rust or C toolchain. Upstream currently tests Python 3.9+ on ARM64 macOS and x86-64/ARM Linux. Intel macOS support was removed in 49.0.0; this note does not assert compatibility there. [Installation guidance](https://cryptography.io/en/50.0.1/installation/), [release changes](https://cryptography.io/en/stable/changelog/).

On CPython 3.12/3.13, the package adds `cffi>=2.0.0`; `cffi` adds `pycparser`. Current releases are `cffi==2.1.1` and `pycparser==3.0`, both requiring Python >=3.10. These are compatible candidate transitive versions, not a completed lock resolution. No SSH extra is needed; the conditional typing-extensions dependency only applies below Python 3.11. The backend lock currently contains none of these three packages. [Cryptography metadata](https://pypi.org/pypi/cryptography/50.0.1/json), [CFFI metadata](https://pypi.org/pypi/cffi/2.1.1/json), [pycparser metadata](https://pypi.org/pypi/pycparser/3.0/json).

## Exact signing semantics and security

Existing `apps/web/app/lib/maskinporten.ts:217` fixes the JWT header to RS256; line 226 signs the ASCII `base64url(header).base64url(claims)` input with Node's RSA-SHA256. The Python equivalent is `private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())`, followed by unpadded base64url encoding. RS256 means RSASSA-PKCS1-v1_5 with SHA-256. Digdir explicitly supports RS256, RS384 and RS512; preserve RS256, registered `kid`, and existing grant claims/time bounds. PSS is upstream's preference for new protocols but would change this existing protocol. [JWA specification, section 3.3](https://www.rfc-editor.org/rfc/rfc7518.html#section-3.3), [RSA API](https://cryptography.io/en/50.0.1/hazmat/primitives/asymmetric/rsa/#signing), [Digdir JWT grant](https://docs.digdir.no/docs/Maskinporten/maskinporten_protocol_jwtgrant.html).

Load the configured unencrypted PEM through `serialization.load_pem_private_key(pem_bytes, password=None)`, keep RSA validation enabled, and explicitly require an `rsa.RSAPrivateKey`. Preserve PKCS#1 and PKCS#8 input support. Convert malformed/encrypted/non-RSA/unsupported-key failures into the adapter's bounded configuration failure before network I/O; never include key material in exceptions. RFC 7518 requires RSA keys at least 2048 bits. [Key loading and validation](https://cryptography.io/en/50.0.1/hazmat/primitives/asymmetric/serialization/#cryptography.hazmat.primitives.serialization.load_pem_private_key), [JWA key requirement](https://www.rfc-editor.org/rfc/rfc7518.html#section-3.3).

Upstream security support covers its current release and main branch. Version 50.0.1 updates bundled OpenSSL to 4.0.2; 50.0.0 also fixed an unrelated PKCS#7 decryption oracle. Pinning older releases would lose current upstream security support. Upstream recommends vulnerability scanning and prompt upgrades when bundled OpenSSL changes; no dependency audit was executed here. [Security policy](https://cryptography.io/en/50.0.1/security/), [50.0.1 changelog](https://cryptography.io/en/stable/changelog/#id1).

After the claim and implementation assignment, update only the backend manifest/lock through the repository's uv workflow, then validate locked installation and focused RSA grant tests with disposable test keys: signature verification, tampering rejection, both PEM formats, non-RSA/malformed/encrypted/undersized key rejection, and preserved claims/time/JTI behavior. This is local conformance proof; live Maskinporten authorization remains a separate prerequisite.
