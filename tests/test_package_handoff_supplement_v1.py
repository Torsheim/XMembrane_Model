from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/package_handoff_supplement_v1.py"
RELEASE = ROOT / "deliverables/current/2026-09-03_handoff_v1"


def load_packager():
    spec = importlib.util.spec_from_file_location("package_handoff_supplement_v1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    shutil.which("pdftotext") is None or shutil.which("pdfinfo") is None,
    reason="Poppler pdftotext/pdfinfo are required for full handoff claim verification",
)
def test_handoff_supplement_verifies_without_writes() -> None:
    module = load_packager()
    manifest_before = (RELEASE / "MANIFEST.json").read_bytes()
    checksums_before = (RELEASE / "SHA256SUMS").read_bytes()

    result = module.run(check_only=True)

    assert result == {
        "status": "PASS",
        "release_id": "XMEMBRANE-2026-09-03-HANDOFF-V1",
        "payload_files": 37,
        "checksum_entries": 38,
        "pptx_slides": 31,
        "pdf_pages": 31,
    }
    assert (RELEASE / "MANIFEST.json").read_bytes() == manifest_before
    assert (RELEASE / "SHA256SUMS").read_bytes() == checksums_before


def test_handoff_manifest_is_allowlisted_and_timestamp_free() -> None:
    module = load_packager()
    manifest = json.loads((RELEASE / "MANIFEST.json").read_text(encoding="utf-8"))
    paths = {record["path"] for record in manifest["files"]}

    assert paths == set(module.expected_payload())
    assert not any(path.startswith("presentations/rendered/") for path in paths)
    assert manifest["excluded_local_scratch"] == ["presentations/rendered/"]
    assert manifest["authority"].startswith("post-V10 supplemental handoff")
    assert manifest["governing_v10_source_revision"] == (
        "805ae087a7f3e133444c93f9fbb72856863754bf"
    )
    assert not any("timestamp" in key.casefold() or "created" in key.casefold() for key in manifest)
    assert all(record["mode"] == "0644" for record in manifest["files"])
