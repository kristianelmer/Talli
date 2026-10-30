"""Shared approval byte encoding, document projection and predecessor identity.

No version selection, evidence validation or admission policy lives here. The
legacy caller preserves its validation order around these deterministic steps.
"""
from collections.abc import Mapping
import hashlib
import json

from . import public as rf
from .year_source import _sha, _uuid


def _require(condition: bool) -> None:
    if not condition:
        raise rf.Rf1086ProductionError("basis_unavailable")


def _bytes(value: str) -> bytes:
    # Reject invalid Unicode instead of replacing bytes in an approval identity.
    return value.encode("utf-8", errors="strict")


def _hash(value: str) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _canonical(value) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _documents(preview):
    # Names remain byte-exact stable IDs. Never trim, normalize, parse as
    # UUIDs, or use insertion order, which could reassign journal operations.
    names = tuple(preview.underskjema_xml)
    _require(all(isinstance(name, str) and bool(name.strip()) and "\x00" not in name for name in names))
    names = tuple(sorted(names, key=_bytes))
    # The existing journal limits operation names to 120 characters. Stable
    # derived keys fit that contract without narrowing shareholder IDs.
    keys = {name: "source_" + _hash("rf1086-source-shareholder-v1:" + name) for name in names}
    _require(len(set(keys.values())) == len(names))
    order = tuple(keys[name] for name in names)
    xml = {keys[name]: preview.underskjema_xml[name] for name in names}
    documents = [{"name": "hovedskjema", "sha256": _hash(preview.hovedskjema_xml)}]
    documents.extend({"name": "underskjema_" + keys[name], "shareholderId": name,
                      "sha256": _hash(preview.underskjema_xml[name])} for name in names)
    return order, xml, documents


def _predecessor(value):
    predecessor = None
    if value is not None:
        prior = value
        _require(isinstance(prior, rf.Rf1086SourceCorrectionPredecessor)
                 and isinstance(prior.submission_id, rf.SubmissionId)
                 and isinstance(prior.reason, str) and bool(prior.reason.strip()))
        predecessor = {"submissionId": _uuid(prior.submission_id.value),
                       "manifestSha256": _sha(prior.manifest_sha256), "reason": prior.reason}
    return predecessor
