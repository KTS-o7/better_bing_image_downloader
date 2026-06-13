"""JSONL manifest writer for image search runs (v3.5.0+).

A small, append-only writer that streams one JSON object per line
to a file. Used by ``Downloader.search`` when ``manifest=True`` is
passed.

The writer is intentionally minimal:

- One line per ``append()`` call.
- Records are filtered to a configured field list before being
  written (so engines can pass full records).
- File is opened in append mode with line buffering, so a crash
  in the middle of a run leaves a valid (partial) manifest.
- The writer is **not** thread-safe; ``Downloader.search`` is
  single-threaded for record-append.

Public surface:

- :class:`ManifestWriter` — the writer
- :class:`ManifestFieldError` — raised when an unknown field is requested
- :data:`DEFAULT_MANIFEST_FIELDS` — the default 10-field set
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

# Default field set: "core + provenance" (10 fields).
# These are the fields written to the manifest when the user does
# not supply an explicit ``manifest_fields`` list. The order is
# stable and is the on-disk schema; downstream tools can rely on it.
DEFAULT_MANIFEST_FIELDS: list[str] = [
    "index",
    "status",
    "url",
    "file",
    "md5",
    "error",
    "engine",
    "query",
    "source_page",
    "downloaded_at",
]


class ManifestFieldError(ValueError):
    """Raised when an unknown field is requested in ``manifest_fields``.

    Subclasses :class:`ValueError` so callers that catch ``ValueError``
    (Liskov substitution) keep working.
    """


class ManifestWriter:
    """Append-only JSONL writer for search run records.

    Each call to :meth:`append` writes one line of JSON. Records are
    filtered to the configured :attr:`fields` list before being
    written, so callers can pass a fully-populated record dict and
    rely on the writer to project it.

    The writer is not thread-safe; it is intended for use from the
    single-threaded ``Downloader.search`` main loop. Engines do
    their own parallel image downloads, but record-appending happens
    in the main thread.

    Example
    -------

    >>> from pathlib import Path
    >>> from better_bing_image_downloader.manifest import ManifestWriter
    >>> with ManifestWriter(Path("out.jsonl")) as w:
    ...     w.append({"index": 1, "status": "ok", "url": "https://x/a.jpg"})
    ...     w.append({"index": 2, "status": "error", "error": "NetworkError"})
    """

    def __init__(
        self,
        path: str | os.PathLike,
        fields: list[str] | None = None,
        flush_every: int = 1,
    ) -> None:
        if fields is None:
            fields = list(DEFAULT_MANIFEST_FIELDS)
        unknown = [f for f in fields if f not in DEFAULT_MANIFEST_FIELDS]
        if unknown:
            raise ManifestFieldError(
                f"unknown manifest field(s) {unknown!r}; " f"valid: {DEFAULT_MANIFEST_FIELDS}"
            )
        if flush_every < 1:
            raise ValueError("flush_every must be >= 1")
        self._fields = list(fields)
        self._flush_every = flush_every
        self._pending = 0
        self._closed = False
        # Ensure parent dir exists (match output_dir semantics in base.py).
        resolved = Path(path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered append mode. buffering=1 = line buffered.
        # ``close()`` is the canonical way to release the handle; the
        # writer is also usable as a context manager.
        self._fp: IO[str] = open(  # noqa: SIM115 - managed via close()/__exit__
            resolved, "a", encoding="utf-8", buffering=1
        )

    @property
    def fields(self) -> list[str]:
        """The list of field names that will appear in each written line."""
        return list(self._fields)

    def append(self, record: dict) -> None:
        """Write one record as a JSON line. Filters to configured fields.

        A failure inside ``json.dumps`` or the underlying file write
        is logged via :mod:`logging` and swallowed: manifest writes
        must never crash a search.
        """
        if self._closed:
            return
        try:
            filtered = {k: record.get(k) for k in self._fields}
            line = json.dumps(filtered, ensure_ascii=False, separators=(",", ":"))
            self._fp.write(line + "\n")
            self._pending += 1
            if self._pending >= self._flush_every:
                self._fp.flush()
                self._pending = 0
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warning("manifest write failed: %s", exc)

    def close(self) -> None:
        """Flush and close the file. Idempotent."""
        if self._closed:
            return
        try:
            self._fp.flush()
            self._fp.close()
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warning("manifest close failed: %s", exc)
        self._closed = True

    def __enter__(self) -> ManifestWriter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
