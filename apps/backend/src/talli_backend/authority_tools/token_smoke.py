"""The existing explicitly configured token smoke command, with redacted output."""

import asyncio
import json
import sys

from talli_backend.adapters.maskinporten import MaskinportenTokenError
from talli_backend.authority_tools._grant import CliGrantConfiguration, request_token, token_summary


async def run(environment=None, *, transport=None) -> dict:
    token = await request_token(CliGrantConfiguration.from_environment(environment), transport=transport)
    try:
        return {"ok": True, **token_summary(token)}
    finally:
        token.discard()


def main() -> int:
    try:
        print(json.dumps(asyncio.run(run()), separators=(",", ":")))
        return 0
    except MaskinportenTokenError as error:
        output = {"ok": False, "code": error.code, "status": error.status, "message": str(error)}
    except Exception:
        output = {"ok": False, "code": "local_configuration_error", "status": None,
                  "message": "Maskinporten local configuration is invalid."}
    print(json.dumps(output, separators=(",", ":")), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
