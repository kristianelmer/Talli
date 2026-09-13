#!/usr/bin/env python3
"""Opt-in, offline replay of one digest-verified historical RF no-activity case.

Private inputs are explicit arguments and are never printed or copied into the
repository. This verifier is not a provider harness or a mandatory private-data
fixture. Run with the canonical backend installed or on PYTHONPATH.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


class ReplayVerificationError(Exception):
    """Only a fixed diagnostic code, never a source value or parser detail."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ReplayVerificationError(code)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reject_network(event: str, _args: object) -> None:
    if event in ("socket.connect", "socket.getaddrinfo", "http.client.connect"):
        raise ReplayVerificationError("offline_network_forbidden")


def original_documents(directory: Path) -> tuple[Path, Path]:
    files = tuple(directory.glob("*.xml"))
    children = tuple(path for path in files if path.name.startswith("1086U-") and path.stem != "1086U-")
    main = directory / "1086H.xml"
    require(len(files) == 2 and main in files and len(children) == 1, "original_two_document_extent_required")
    return main, children[0]


def private_write(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(value)
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, "private_output_mode_required")


def replay(args: argparse.Namespace) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    require(re.fullmatch(r"[0-9a-f]{64}", args.expected_case_sha256) is not None, "invalid_expected_case_digest")
    require(not args.output_directory.exists(), "output_directory_must_be_new")
    historical_raw = args.historical_evidence.read_bytes()
    historical = json.loads(historical_raw)
    require(historical["status"] == "accepted", "accepted_historical_receipt_required")
    expected_main = historical["payloadHashes"]["hovedskjema"]
    expected_children = historical["payloadHashes"]["underskjema"]
    require(len(expected_children) == 1 and historical["archive"]["documentCount"] == 2, "original_one_child_receipt_required")
    expected = (expected_main, expected_children[0])
    require(all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in expected), "invalid_historical_document_digest")
    require(sorted(historical["archive"]["documentHashes"]) == sorted(expected), "historical_archive_digest_mismatch")

    # Verify every original byte source before importing or invoking the parser.
    raw_case = args.case.read_bytes()
    require(sha256(raw_case) == args.expected_case_sha256, "original_case_digest_mismatch")
    originals = original_documents(args.xml_directory)
    preflight = original_documents(args.preflight_xml_directory)
    require(originals[1].name == preflight[1].name, "original_child_identity_mismatch")
    raw_originals = tuple(path.read_bytes() for path in originals)
    raw_preflight = tuple(path.read_bytes() for path in preflight)
    require(tuple(map(sha256, raw_originals)) == expected, "historical_xml_digest_mismatch")
    require(tuple(map(sha256, raw_preflight)) == expected, "historical_preflight_digest_mismatch")
    require(isinstance(json.loads(raw_case), dict), "single_case_object_required")

    from talli_backend.modules.shareholder_register_filing.public import (
        assess_rf1086_readiness, generate_rf1086_documents, parse_rf1086_case, rf1086_xml_schema,
    )

    case = parse_rf1086_case(raw_case.decode("utf-8"))
    require(case.company.income_year == historical["incomeYear"] and not case.events, "original_no_activity_scope_required")
    require(len(case.shareholders) == len(case.shareholder_snapshots) == 1, "one_original_shareholder_required")
    readiness = assess_rf1086_readiness(case)
    require(readiness.is_ready, "canonical_readiness_not_ready")
    documents = generate_rf1086_documents(case)
    child_identity = originals[1].stem.removeprefix("1086U-")
    require(list(documents.underskjema_xml) == [child_identity], "original_child_identity_required")
    generated = (documents.hovedskjema_xml.encode("utf-8"), documents.underskjema_xml[child_identity].encode("utf-8"))
    require(generated == raw_originals == raw_preflight, "historical_byte_mismatch")
    repeated = generate_rf1086_documents(case)
    require(generated == (repeated.hovedskjema_xml.encode("utf-8"), repeated.underskjema_xml[child_identity].encode("utf-8")), "nondeterministic_output")

    args.output_directory.mkdir(mode=0o700)
    require(stat.S_IMODE(args.output_directory.stat().st_mode) == 0o700, "private_directory_mode_required")
    comparisons = []
    for index, kind in enumerate(("hovedskjema", "underskjema")):
        document, schema = (args.output_directory / (kind + suffix) for suffix in (".xml", ".xsd"))
        private_write(document, generated[index])
        private_write(schema, rf1086_xml_schema(kind))
        checked = subprocess.run(
            [str(args.xmllint), "--nonet", "--noout", "--schema", str(schema), str(document)],
            capture_output=True, env={"PATH": "/usr/bin:/bin"}, check=False, timeout=30,
        )
        require(checked.returncode == 0, "bundled_xsd_validation_failed")
        comparisons.append({
            "document": kind, "generatedSha256": sha256(generated[index]),
            "historicalXmlSha256": sha256(raw_originals[index]),
            "historicalPreflightXmlSha256": sha256(raw_preflight[index]),
            "recordedAuthoritySha256": expected[index], "bytes": len(generated[index]),
            "exactByteEquality": True, "bundledSchemaSha256": sha256(schema.read_bytes()),
            "bundledSchemaValidation": "pass",
        })
    require(args.case.read_bytes() == raw_case and args.historical_evidence.read_bytes() == historical_raw, "original_source_modified")
    require(tuple(path.read_bytes() for path in originals) == raw_originals and tuple(path.read_bytes() for path in preflight) == raw_preflight, "historical_xml_modified")
    require(not any(name.startswith(("holding_core", "holding_cli", "talli_backend.authority_tools", "talli_backend.adapters")) for name in sys.modules), "noncanonical_or_provider_module_loaded")
    source_files = {}
    for module in tuple(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and Path(path).resolve().is_relative_to(root / "apps/backend/src/talli_backend"):
            resolved = Path(path).resolve()
            source_files[str(resolved.relative_to(root))] = sha256(resolved.read_bytes())
    require(bool(source_files), "canonical_checkout_source_required")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, check=True,
                          env={"PATH": "/usr/bin:/bin"}, timeout=10).stdout.decode().strip()
    historical_path = args.historical_evidence.resolve()
    return {
        "schemaVersion": 1, "issue": "#151", "acceptanceCriterion": "A1",
        "status": "exact-historical-payload-regeneration-pass", "observedAt": datetime.now(timezone.utc).isoformat(),
        "historicalEvidence": str(historical_path.relative_to(root)) if historical_path.is_relative_to(root) else None,
        "historicalEvidenceSha256": sha256(historical_raw), "historicalGeneratorRevision": historical["codeCommit"],
        "testedHead": head, "testedSourceState": "working-tree-source-hashes-below",
        "originalCaseSha256": args.expected_case_sha256, "caseCount": 1, "incomeYear": case.company.income_year,
        "eventCount": 0, "shareholderCount": 1, "childDocumentCount": 1, "canonicalReadiness": readiness.status,
        "canonicalPublicEntry": "talli_backend.modules.shareholder_register_filing.public",
        "operations": ["parse_rf1086_case", "assess_rf1086_readiness", "generate_rf1086_documents", "rf1086_xml_schema"],
        "repeatGenerationByteEquality": True, "documents": comparisons, "sourceFiles": dict(sorted(source_files.items())),
        "producerPath": str(Path(__file__).resolve().relative_to(root)), "producerSha256": sha256(Path(__file__).read_bytes()),
        "pythonVersion": sys.version.split()[0], "providerCalls": 0, "credentialAccess": False,
        "historicalSourceModified": False, "privateOutputModes": {"directory": "0700", "documentsAndSchemas": "0600"},
        "rawInputsOrXmlCommitted": False,
        "limits": ["Offline replay of one original historical no-activity case, not a new authority acceptance run.",
                   "No provider, credentials, database, production activation or commercial decision was used.",
                   "The full #151 two-pass exit and protected integration remain separate requirements."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("case", "historical-evidence", "xml-directory", "preflight-xml-directory", "output-directory"):
        parser.add_argument("--" + argument, type=Path, required=True)
    parser.add_argument("--expected-case-sha256", required=True)
    parser.add_argument("--xmllint", type=Path, default=Path("/usr/bin/xmllint"))
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    sys.addaudithook(reject_network)
    try:
        receipt = replay(args)
        private_write(args.output_directory / "receipt.json", (json.dumps(receipt, indent=2) + "\n").encode())
        print(json.dumps({"status": receipt["status"], "caseCount": 1, "documentCount": 2}))
        return 0
    except Exception as error:
        # No parser validation text, XML, private path or subprocess output leaves
        # this boundary, including a failure after private files were generated.
        code = str(error) if isinstance(error, ReplayVerificationError) else "offline_replay_failed"
        print(json.dumps({"status": "failed", "code": code}))
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
