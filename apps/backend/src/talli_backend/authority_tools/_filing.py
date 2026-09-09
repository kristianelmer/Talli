"""Private frozen filing-tool mechanics; no API, arbitrary endpoint or authority policy."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[5]
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


class FilingToolError(Exception):
    def __init__(self, message: str, *, code: str, status: int | None = None,
                 retryable: bool = False, validation_codes: list[str] | None = None):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable
        self.correlation_id = None
        self.validation_codes = validation_codes or []

    def evidence(self):
        return {"code": self.code, "status": self.status, "correlationId": None,
                "retryable": self.retryable, "message": str(self)}


def required(environment, name):
    value = environment.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def check_private_key_file(environment):
    """Preserve the tax CLI's pre-try file check; the grant helper rechecks on read."""
    path = Path(required(environment, "TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"))
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError("Maskinporten private-key file must be a mode-0600 regular file.")
    except OSError:
        raise ValueError("Maskinporten private-key file could not be read.") from None


def text(value, fallback="", *, secrets=()):
    if not isinstance(value, str):
        return fallback
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"-----BEGIN [\s\S]*?-----END [^-]+-----", "[redacted]", value)
    value = re.sub(r"(?i)Bearer\s+\S+", "[redacted]", value)
    value = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted]", value)
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", value)).strip()[:500]


def obj(value):
    return value if isinstance(value, dict) else {}


def opaque(value):
    if not isinstance(value, str) or not value or re.search(r"\s", value):
        raise ValueError("Authority access token must be opaque.")
    return value


def valid(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"Invalid {label}.")
    return value


def instance_id(value):
    return valid(value, rf"[0-9]+/{UUID_PATTERN}", "Altinn instance id")


def data_id(value):
    return valid(value, UUID_PATTERN, "Altinn data id")


def org_number(value):
    return valid(value, r"[0-9]{9}", "organization number")


def income_year(value):
    if type(value) is not int or not 2000 <= value <= 2100:
        raise ValueError("Income year must be an integer between 2000 and 2100.")
    return value


def case_income_year(value):
    """Preserve the standalone scripts' Number(value)/Number.isInteger check."""
    if isinstance(value, list):
        def array_text(items):
            return ",".join("" if item is None else array_text(item) if isinstance(item, list)
                else "true" if item is True else "false" if item is False
                else "[object Object]" if isinstance(item, dict) else str(item) for item in items)
        value = array_text(value)
    if isinstance(value, str):
        # ECMAScript WhiteSpace/LineTerminator; Python accepts additional chars.
        value = value.strip("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")
        if not value:
            value = 0
        elif re.fullmatch(r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+", value):
            value = int(value, 0)
        elif not re.fullmatch(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
            raise ValueError("Authority case income year is invalid.")
    try:
        number = float(0 if value is None else value)
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError()
        return int(number)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Authority case income year is invalid.") from None


def xml(value):
    if not isinstance(value, str) or not value.lstrip().startswith("<"):
        raise ValueError("XML is required.")
    return value


def iso(value):
    value = text(value)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        return None


def now():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def git_commit():
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _parse_json(value):
    """Keep the frozen tools' JSON.parse syntax, including ignored fields."""
    def reject_constant(_):
        raise ValueError("Non-standard JSON constant.")
    return json.loads(value, parse_constant=reject_constant)


def read_evidence(path):
    try:
        result = _parse_json(path.read_text())
        if result is not None and (not isinstance(result, dict) or not result):
            raise ValueError("Existing authority evidence is invalid.")
        return result
    except FileNotFoundError:
        return None


def write_evidence(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def payload(operation: str, value: dict[str, Any]):
    if operation not in {"annual_accounts", "company_tax", "company_tax_envelope",
                         "company_tax_validation_envelope", "company_tax_validation_summary"}:
        raise ValueError("Unknown fixed payload operation.")
    # Deliberately do not inherit NODE_OPTIONS or any provider/other environment secret.
    result = subprocess.run(["node", "--experimental-strip-types", str(ROOT / "scripts/authority-tool-payload.mjs")],
        input=json.dumps({"operation": operation, "input": value}), cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "LANG": "en_US.UTF-8"},
        text=True, capture_output=True, timeout=30)
    if result.returncode or len(result.stdout.encode()) > MAX_RESPONSE_BYTES:
        raise ValueError("Local authority payload generation failed.")
    return _parse_json(result.stdout)


def validate_xml(documents, schemas=None):
    with tempfile.TemporaryDirectory(prefix="talli-authority-filing-") as directory:
        for filename, content in documents.items():
            path = Path(directory) / filename
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
            arguments = ["xmllint", "--noout"]
            if schemas:
                arguments += ["--schema", str(schemas[filename])]
            result = subprocess.run([*arguments, str(path)], capture_output=True, timeout=30)
            if result.returncode:
                raise ValueError("Local authority XML validation failed.")


class FixedTransport:
    """Bounded private mechanics called only with the fixed filing adapter endpoints."""
    def __init__(self, prefix, error_type, *, transport=None, timeout_ms=20_000, secrets=()):
        if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 120000:
            raise ValueError("Authority timeout must be between 1000 and 120000 milliseconds.")
        self._prefix, self._error_type = prefix, error_type
        self._transport, self._timeout = transport, timeout_ms / 1000
        self._secrets = secrets

    def safe(self, value, fallback=""):
        return text(value, fallback, secrets=self._secrets)

    async def _request(self, url, method, token, *, accept="application/json", content_type=None, body=None, headers=None):
        request_headers = {"authorization": f"Bearer {opaque(token)}", "accept": accept}
        if content_type:
            request_headers["content-type"] = content_type
        request_headers.update(headers or {})
        try:
            async with asyncio.timeout(self._timeout), httpx.AsyncClient(
                transport=self._transport, follow_redirects=False, timeout=self._timeout, trust_env=False,
            ) as client:
                async with client.stream(method, url, headers=request_headers,
                                         content=body.encode("utf-8") if isinstance(body, str) else body) as response:
                    status, response_headers = response.status_code, response.headers
                    if 300 <= status < 400:
                        raise self._error_type("Authority redirects are refused.", code=self._prefix+"_REDIRECT_REFUSED", status=status)
                    if not 200 <= status < 300:
                        # No remote title/code/trace is reflected: it can contain a token or submitted XML.
                        raise self._error_type("Authority request was rejected.", code=f"{self._prefix}_HTTP_{status}",
                            status=status, retryable=status in (401, 408, 425, 429) or status >= 500)
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise self._error_type("Authority response is too large.", code=self._prefix+"_RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    # Fetch Response.text() strips one initial UTF-8 BOM and
                    # replaces malformed sequences for JSON, XML and token text.
                    raw = b"".join(chunks).decode("utf-8-sig", errors="replace")
        except (httpx.HTTPError, TimeoutError):
            raise self._error_type("Authority request failed before a response was received.",
                code=self._prefix+"_NETWORK_ERROR", retryable=True) from None
        if any(secret and secret in raw for secret in self._secrets):
            raise self._error_type("Authority response contains reflected credentials.", code=self._prefix+"_RESPONSE_INVALID")
        try:
            parsed = _parse_json(raw) if raw else {}
        except ValueError:
            parsed = {}
        return raw, parsed, status, response_headers


def local_error(prefix):
    return {"code": prefix+"_LOCAL_OR_RESPONSE_ERROR", "status": None, "correlationId": None,
            "retryable": False, "message": "Local configuration, payload or authority response is invalid."}
