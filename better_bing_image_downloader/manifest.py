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
- :data:`DEFAULT_MANIFEST_FIELDS` — the default field set (11 fields)

The on-disk record format is the public contract; it is described by
``docs/manifest.schema.json`` (JSON Schema Draft 2020-12) in the
repository.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import ImageEngine

logger = logging.getLogger(__name__)

# Default field set: "core + provenance + caption" (11 fields).
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
    "caption",
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


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with a trailing 'Z'.

    Used by the manifest writer to stamp each record's
    ``downloaded_at`` field. Format: ``YYYY-MM-DDTHH:MM:SSZ``.

    Moved here from ``downloader.py`` in the downloader split (#83);
    re-exported there so existing imports keep working.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _ManifestContext:
    """Invocation-local manifest state for a single ``search()`` call.

    Holds the writer, the engine/query provenance metadata, and the
    1-based record counter. A fresh instance is created at the top of
    every ``search()`` call and closed over by the success/error/skip
    hooks — it is deliberately NOT stored on the ``Downloader``
    instance, so a nested ``search()`` fired from an ``on_image``
    hook, or two threads running ``search()`` concurrently on the
    same ``Downloader``, each get independent writers and counters.

    Moved here from ``downloader.py`` in the downloader split (#83).
    """

    __slots__ = ("writer", "engine_name", "query", "index")

    def __init__(self, writer: ManifestWriter, engine_name: str, query: str) -> None:
        self.writer = writer
        self.engine_name = engine_name
        self.query = query
        # 1-based record counter, incremented by
        # ``_append_manifest_record`` on every record.
        self.index = 0


def _append_manifest_record(
    manifest_ctx: _ManifestContext,
    status: str,
    url: str,
    file_path: Path | None,
    md5: str | None,
    error: BaseException | None,
    engine_obj: ImageEngine,
) -> None:
    """Build a manifest record dict and append it to the context's writer.

    Called from the success and error paths inside ``Downloader.search``
    when ``manifest=True`` was passed. The record is filtered to
    the writer's configured fields automatically.

    ``file_path`` is stored relative to ``output_dir`` (i.e. as
    ``"<query>/Image_1.jpg"``) so the manifest is portable
    across machines. If the relative-to conversion fails (e.g.
    the engine wrote outside ``output_dir``), the basename is
    used as a fallback.

    Moved here from ``downloader.py`` in the downloader split (#83).
    """
    # ``index`` is 1-based and counts every record (success or
    # failure). We keep a per-search counter on the invocation-local
    # context instead of deriving the index from the engine's internal
    # ``download_count``: the engine only advances that counter on
    # a successful save, so two consecutive error/skip records
    # would otherwise share the same ``index`` value.
    manifest_ctx.index += 1
    index = manifest_ctx.index
    # Resolve file path relative to output_dir.
    file_rel: str | None = None
    if file_path is not None:
        try:
            file_rel = str(file_path.resolve().relative_to(Path.cwd()))
        except ValueError:
            file_rel = file_path.name
    manifest_ctx.writer.append(
        {
            "index": index,
            "status": status,
            "url": url,
            "file": file_rel,
            "md5": md5,
            "error": type(error).__name__ if error is not None else None,
            "engine": manifest_ctx.engine_name,
            "query": manifest_ctx.query,
            "source_page": getattr(engine_obj, "last_page_url", None),
            "downloaded_at": _utcnow_iso(),
            # ``caption`` (v3.9.0+): title/alt text from the search
            # backend, looked up from the engine's captions dict.
            # None for error/skipped records and engines without
            # caption support.
            "caption": getattr(engine_obj, "captions", {}).get(url),
        }
    )
