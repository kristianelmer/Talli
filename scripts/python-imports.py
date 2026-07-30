"""Extract normalized Python imports for architecture enforcement.

The checker passes source text over stdin so this helper can also inspect copied
fixtures.  `ast` handles aliases, comma-separated imports, and parenthesized or
otherwise multiline import statements without attempting to emulate Python
grammar in JavaScript.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from typing import Any


def package_for(path: str, source_root: str) -> str:
    relative = os.path.relpath(path, source_root)
    parts = relative.split(os.sep)
    if not parts or parts[-1] == ".." or relative.startswith(f"..{os.sep}"):
        raise ValueError(f"source is outside package root: {path}")
    stem, extension = os.path.splitext(parts[-1])
    if extension != ".py":
        raise ValueError(f"source is not Python: {path}")
    package_parts = parts[:-1] if stem == "__init__" else [*parts[:-1], stem]
    return ".".join(package_parts if stem == "__init__" else package_parts[:-1])


def resolved_from_import(node: ast.ImportFrom, package: str) -> str | None:
    if not node.level:
        return node.module
    package_parts = package.split(".") if package else []
    retained = len(package_parts) - (node.level - 1)
    if retained <= 0:
        raise ValueError(f"relative import escapes package: {'.' * node.level}{node.module or ''}")
    prefix = ".".join(package_parts[:retained])
    return ".".join(part for part in [prefix, node.module] if part)


def imports_for(file: dict[str, str], source_root: str) -> dict[str, Any]:
    path = file["path"]
    try:
        tree = ast.parse(file["source"], filename=path)
        package = package_for(path, source_root)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                resolved = resolved_from_import(node, package)
                if resolved:
                    imports.append(resolved)
        symbols = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "function",
                        "decorators": [ast.unparse(decorator) for decorator in node.decorator_list],
                    }
                )
            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "bases": [ast.unparse(base) for base in node.bases],
                        "decorators": [ast.unparse(decorator) for decorator in node.decorator_list],
                    }
                )
        return {"path": path, "imports": imports, "symbols": symbols}
    except (SyntaxError, ValueError) as error:
        return {"path": path, "error": str(error)}


def main() -> None:
    request = json.load(sys.stdin)
    source_root = request["sourceRoot"]
    print(json.dumps({"files": [imports_for(file, source_root) for file in request["files"]]}))


if __name__ == "__main__":
    main()
