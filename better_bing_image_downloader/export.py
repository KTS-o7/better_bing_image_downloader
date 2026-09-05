"""Export ``manifest.jsonl`` files to ML-pipeline formats.

ML users consume manifests through tools that expect specific input
formats — img2dataset wants a plain text file with one URL per line,
Hugging Face ``datasets`` and parquet-native pipelines want Parquet.
This module converts a JSONL manifest (as written by
:class:`better_bing_image_downloader.manifest.ManifestWriter`) into
those formats with one call.

The exporter is deliberately tolerant of partial manifests: blank
lines are skipped, and lines that fail to parse as JSON are logged
via :mod:`logging` and skipped — a crashed run still exports cleanly.

Public surface:

- :func:`export_manifest` — export a manifest to ``url-list`` or
  ``parquet``, returning the number of rows written.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Formats accepted by :func:`export_manifest`.
VALID_EXPORT_FORMATS: tuple[str, ...] = ("url-list", "parquet")


def export_manifest(manifest_path: str | Path, fmt: str, dest: str | Path) -> int:
    """Export a JSONL manifest to an ML-pipeline format.

    Parameters
    ----------
    manifest_path : str | Path
        Path to the ``manifest.jsonl`` file written by a search run.
    fmt : str
        Output format. ``"url-list"`` writes a ``.txt`` file with one
        image URL per line (only ``status == "ok"`` records) — the
        img2dataset-compatible input format. ``"parquet"`` writes ALL
        records (every status) to Parquet; requires the optional
        ``pyarrow`` dependency.
    dest : str | Path
        Destination file path. Parent directories are created if
        needed.

    Returns
    -------
    int
        Number of rows written to ``dest``.

    Raises
    ------
    ValueError
        If ``fmt`` is not one of :data:`VALID_EXPORT_FORMATS`.
    ImportError
        If ``fmt == "parquet"`` and ``pyarrow`` is not installed.

    Example
    -------

    >>> from better_bing_image_downloader import export_manifest
    >>> export_manifest("dataset/red panda/manifest.jsonl", "url-list", "urls.txt")
    42
    """
    if fmt not in VALID_EXPORT_FORMATS:
        raise ValueError(
            f"unknown export format {fmt!r}; valid formats: {', '.join(VALID_EXPORT_FORMATS)}"
        )
    records = list(_iter_records(manifest_path))
    if fmt == "url-list":
        return _write_url_list(records, dest)
    return _write_parquet(records, dest)


def _iter_records(manifest_path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield parsed records from a JSONL manifest.

    Blank lines are skipped. Lines that fail ``json.loads`` are logged
    with :func:`logging.warning` and skipped, so a partial manifest
    from a crashed run never aborts the export.
    """
    resolved = Path(manifest_path).expanduser()
    with open(resolved, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "skipping malformed manifest line %d in %s: %s", lineno, resolved, exc
                )
                continue
            if not isinstance(record, dict):
                logger.warning(
                    "skipping non-object manifest line %d in %s: %r", lineno, resolved, record
                )
                continue
            yield record


def _write_url_list(records: list[dict[str, Any]], dest: str | Path) -> int:
    """Write one URL per line for records with ``status == "ok"``."""
    urls = [r["url"] for r in records if r.get("status") == "ok" and r.get("url")]
    resolved = Path(dest).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(f"{url}\n")
    return len(urls)


def _write_parquet(records: list[dict[str, Any]], dest: str | Path) -> int:
    """Write all records (every status) to a Parquet file via pyarrow."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportError(
            "Parquet export requires pyarrow. Install it with: "
            'pip install "better-bing-image-downloader[parquet]"'
        ) from exc
    resolved = Path(dest).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(records) if records else pa.table({})
    pq.write_table(table, resolved)
    return int(table.num_rows)
