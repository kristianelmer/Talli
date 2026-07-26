"""Read-only live-review helper for the disposable issue #130 prototype."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent
REQUIRED_COMMON = {
    "schemaVersion",
    "kind",
    "name",
    "path",
    "owner",
    "purpose",
    "documentation",
    "publicEntryPoint",
    "dependencies",
    "forbiddenResponsibilities",
    "tests",
    "compatibilityExceptions",
}
REQUIRED_BY_KIND = {
    "backend-capability": {"exports", "owns", "ports"},
    "web-feature": {
        "ownedRoutes",
        "apiOperations",
        "cachePolicy",
        "directBrowserFlows",
    },
}


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def validate_manifest(path: Path) -> dict[str, object]:
    manifest = load_json(path)
    kind = manifest.get("kind")
    if kind not in REQUIRED_BY_KIND:
        raise ValueError(f"{path}: unknown module kind {kind!r}")
    missing = (REQUIRED_COMMON | REQUIRED_BY_KIND[kind]) - manifest.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    if manifest["schemaVersion"] != "1.0":
        raise ValueError(f"{path}: unsupported schemaVersion")
    if not manifest["forbiddenResponsibilities"]:
        raise ValueError(f"{path}: forbiddenResponsibilities must not be empty")
    return manifest


def main() -> None:
    load_json(ROOT / "module.schema.json")
    print((ROOT / "TARGET_TREE.md").read_text(encoding="utf-8"))
    print("\nManifest examples")
    for path in sorted((ROOT / "examples").glob("*/module.json")):
        manifest = validate_manifest(path)
        print(
            f"- {manifest['kind']} {manifest['name']}: "
            f"{manifest['publicEntryPoint']} ({path.relative_to(ROOT)})"
        )
    print("\nReview result: prototype files parse and required ownership fields are present.")


if __name__ == "__main__":
    main()
