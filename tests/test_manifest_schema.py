"""Validate ``manifest.jsonl`` records against ``docs/manifest.schema.json``.

Drift guard (issue #43): if the writer's output ever changes shape
without the published schema being updated, these tests fail loudly.
"""

import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

jsonschema = pytest.importorskip("jsonschema")

from better_bing_image_downloader import Downloader  # noqa: E402
from better_bing_image_downloader import base as _base  # noqa: E402
from better_bing_image_downloader.base import ImageEngine  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "manifest.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _validator(schema: dict):
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


def _run_manifest_search(tmp_path: Path) -> list[dict]:
    """Run a real search (network stubbed) with manifest=True.

    Produces one "ok" record and one "error" record through the real
    writer code path.
    """

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/good.jpg", 1)
            self.download_image("https://example.test/bad.jpg", 2)

    def fake_http_get(self, url, headers=None):
        if "bad" in url:
            raise urllib.error.URLError("boom")
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    manifest_path = tmp_path / "manifest.jsonl"
    dl = Downloader()
    dl.register("fake", FakeEngine)
    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        dl.search(
            "cats",
            limit=2,
            engine="fake",
            output_dir=tmp_path,
            manifest=True,
            manifest_path=str(manifest_path),
        )

    with open(manifest_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_writer_output_validates_against_schema(schema: dict, tmp_path: Path) -> None:
    records = _run_manifest_search(tmp_path)
    assert len(records) == 2
    statuses = sorted(r["status"] for r in records)
    assert statuses == ["error", "ok"]

    validator = _validator(schema)
    for record in records:
        errors = list(validator.iter_errors(record))
        assert errors == [], f"record failed schema validation: {errors}"


def test_skipped_record_validates_against_schema(schema: dict) -> None:
    """A v3.6.0 min_dimension "skipped" record matches the schema."""
    record = {
        "index": 2,
        "status": "skipped",
        "url": "https://example.test/tiny.jpg",
        "file": None,
        "md5": None,
        "error": "BelowMinDimension",
        "engine": "bing",
        "query": "cats",
        "source_page": "https://www.bing.com/images/async?q=cats",
        "downloaded_at": "2026-06-13T15:30:42Z",
        "caption": "A tiny cat thumbnail",
    }
    errors = list(_validator(schema).iter_errors(record))
    assert errors == [], f"skipped record failed schema validation: {errors}"


def test_schema_covers_all_default_fields(schema: dict) -> None:
    """Every DEFAULT_MANIFEST_FIELDS entry is declared in the schema."""
    from better_bing_image_downloader.manifest import DEFAULT_MANIFEST_FIELDS

    props = set(schema["properties"])
    assert set(DEFAULT_MANIFEST_FIELDS) <= props
    assert set(schema["required"]) == set(DEFAULT_MANIFEST_FIELDS)


def test_schema_rejects_unknown_status(schema: dict) -> None:
    record = {
        "index": 1,
        "status": "bogus",
        "url": "https://example.test/a.jpg",
        "file": "cats/Image_1.jpg",
        "md5": "5d41402abc4b2a76b9719d911017c592",
        "error": None,
        "engine": "bing",
        "query": "cats",
        "source_page": None,
        "downloaded_at": "2026-06-13T15:30:42Z",
        "caption": None,
    }
    assert not _validator(schema).is_valid(record)
