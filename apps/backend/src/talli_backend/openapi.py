from __future__ import annotations

import json

from fastapi import FastAPI


def serialize_openapi(app: FastAPI) -> str:
    return json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"
