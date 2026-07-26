from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from talli_backend.main import app  # noqa: E402
from talli_backend.openapi import serialize_openapi  # noqa: E402

OUTPUT = REPOSITORY_ROOT / "contracts" / "openapi" / "talli-v1.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = serialize_openapi(app)

    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            print(f"OpenAPI drift detected: regenerate {OUTPUT.relative_to(REPOSITORY_ROOT)}")
            return 1
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
