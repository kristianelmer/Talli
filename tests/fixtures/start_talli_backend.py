from __future__ import annotations

import asyncio
import os
import re
import socket
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    nonce = os.environ.get("TALLI_READINESS_NONCE", "")
    if re.fullmatch(r"[A-Za-z0-9-]{1,80}", nonce) is None:
        raise SystemExit("invalid readiness nonce")
    port = int(os.environ["TALLI_BACKEND_PORT"])
    repository_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repository_root / "apps" / "backend" / "src"))

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(2_048)
    print(f"TALLI_BACKEND_BOUND:{nonce}", flush=True)

    configuration = uvicorn.Config(
        "talli_backend.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    asyncio.run(uvicorn.Server(configuration).serve(sockets=[listener]))


if __name__ == "__main__":
    main()
