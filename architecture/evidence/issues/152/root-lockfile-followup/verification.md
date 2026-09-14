# Root Python lockfile consistency

Protected CI run 34805023185 rejected uv sync --locked in both jobs before tests: the root lockfile lacked the backend's already-declared ada-url 4.0.0 and PyICU 2.16.2 dependencies. An isolated pinned copy reproduced uv lock --check failure. Regenerating only the root lock adds those two packages and updates backend dependency metadata. Their versions and artifact hashes exactly match the backend lock; every other existing package record is unchanged. The corrected check and a fresh root uv sync --locked pass.

Local complete gate 849f81d4 was deliberately cancelled before its isolated database stage after this CI defect was confirmed. It has zero gate credit. Earlier three failed gates and this failed protected CI attempt remain recorded. Two eligible complete gates and protected integration are still required. No application or SQL behavior changed.
