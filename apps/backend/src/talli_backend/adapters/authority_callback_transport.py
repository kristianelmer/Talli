"""Authenticate the existing cookie-only web callback forwarding boundary.

This key authenticates a server transport, never an Altinn/Maskinporten call.
The independently verified bearer and owned request still determine authority.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable
from uuid import UUID


CALLBACK_PATH = "/api/v1/authority-connections/system-user-callbacks"


class AuthorityCallbackTransport:
    def __init__(self, key: str, *, clock: Callable[[], float] = time.time) -> None:
        self._key = key
        self._clock = clock

    @property
    def configured(self) -> bool:
        return len(self._key.encode("utf-8")) >= 32

    def verify(self, *, request_id: str, bearer: str, proof: str) -> bool:
        if not self.configured or not bearer:
            return False
        try:
            canonical_id = str(UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            return False
        match = re.fullmatch(r"v1:([0-9]{10}):([a-f0-9]{64})", proof)
        if not match:
            return False
        timestamp, signature = match.groups()
        age = self._clock() - int(timestamp)
        if not -5 <= age <= 60:
            return False
        bearer_hash = hashlib.sha256(bearer.encode("utf-8")).hexdigest()
        message = f"v1\nPOST\n{CALLBACK_PATH}\n{canonical_id}\n{bearer_hash}\n{timestamp}"
        expected = hmac.new(
            self._key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


__all__ = ["AuthorityCallbackTransport"]
