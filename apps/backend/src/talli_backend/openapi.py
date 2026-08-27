from __future__ import annotations

import json

from fastapi import FastAPI


def _canonicalize_dependent_required(value: object) -> None:
    if isinstance(value, dict):
        dependent = value.get("dependentRequired")
        if isinstance(dependent, dict):
            for properties in dependent.values():
                if isinstance(properties, list) and all(
                    isinstance(property_name, str) for property_name in properties
                ):
                    properties.sort()
        for nested in value.values():
            _canonicalize_dependent_required(nested)
    elif isinstance(value, list):
        for nested in value:
            _canonicalize_dependent_required(nested)


def serialize_openapi(app: FastAPI) -> str:
    contract = app.openapi()
    _canonicalize_dependent_required(contract)
    return json.dumps(
        contract,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"
