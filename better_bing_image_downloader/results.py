"""Public result types for the embeddable API (v3.2.0+).

``ImageResult`` is the value object returned for each successful image
download; ``Result`` aggregates a complete search run.

These are plain ``dataclass``-style classes (built on
``typing.NamedTuple`` for Python 3.8+ compatibility) so they are:

- immutable (callers can't accidentally mutate a result)
- hashable (so a list of ImageResults can be deduplicated)
- picklable (so results can cross process boundaries)
- repr-able (so log lines and stack traces are readable)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from .base import ImageEngine


class ImageResult(NamedTuple):
    """A single image saved by a search run.

    Attributes
    ----------
    path : Path
        Where the image was written on disk. Always inside the
        ``output_dir`` of the parent :class:`Result`.
    source_url : str
        The URL the image was downloaded from. May be the original
        search-result URL or a redirect target.
    engine : str
        Name of the engine that produced this image
        (``"bing"``, ``"duckduckgo"``, or a user-registered name).
    query : str
        The search query string.
    image_index : int
        The 1-based index assigned to this image within the run
        (e.g. ``Image_1.jpg``, ``Image_2.jpg``).
    size_bytes : int
        Size of the saved file in bytes.
    mime_type : str
        Detected MIME type (``"image/jpeg"``, ``"image/png"`` etc.).
    """

    path: Path
    source_url: str
    engine: str
    query: str
    image_index: int
    size_bytes: int
    mime_type: str


class Result:
    """Aggregated outcome of a :meth:`Downloader.search` call.

    Attributes
    ----------
    query : str
        The search query.
    engine : str
        Engine name that handled the run.
    output_dir : Path
        Directory images were written into.
    images : list[ImageResult]
        Every image that was newly saved by this run (does not include
        files that were already on disk from a previous run).
    skipped : int
        Number of files that were skipped: either because they already
        existed (``force_replace=False`` and a file with that index
        was present) or, as of v3.6.0, because they were smaller than
        ``min_dimension`` on either side.
    errors : list[tuple[str, BaseException]]
        ``(url, exception)`` pairs for each download that failed.
    no_results_found : bool
        ``True`` if the engine reported it found zero candidate URLs
        (i.e. the search backend returned no results). ``False`` if
        the engine found at least one URL, even if all of them were
        skipped (resume) or failed. This distinguishes
        "search returned nothing" from "search returned stuff but
        nothing was saved" — a distinction that was invisible in
        3.2.0 and earlier.
    cancelled : bool
        ``True`` if the search was aborted via a :class:`CancelToken`
        before reaching the requested limit. The ``images``,
        ``skipped``, and ``errors`` lists reflect whatever was
        completed up to the cancellation point.
    manifest_path : str | None
        Absolute path to the JSONL manifest file written during the
        run, or ``None`` if ``manifest=False`` was passed to
        :meth:`Downloader.search`. The manifest contains one JSON
        record per attempted download (success or failure), with
        status, URL, file path, MD5, error class, and provenance
        metadata. Useful for ML dataset preparation pipelines.
    """

    __slots__ = (
        "query",
        "engine",
        "output_dir",
        "images",
        "skipped",
        "errors",
        "no_results_found",
        "cancelled",
        "manifest_path",
        "_engine",
    )
    _engine: ImageEngine | None  # type annotation for mypy

    def __init__(
        self,
        query: str,
        engine: str,
        output_dir: Path,
        images: list[ImageResult] | None = None,
        skipped: int = 0,
        errors: list[tuple[str, BaseException]] | None = None,
        no_results_found: bool = False,
        cancelled: bool = False,
        manifest_path: str | None = None,
    ) -> None:
        self.query = query
        self.engine = engine
        self.output_dir = output_dir
        self.images: list[ImageResult] = list(images) if images else []
        self.skipped = int(skipped)
        self.errors: list[tuple[str, BaseException]] = list(errors) if errors else []
        # ``no_results_found`` is True if the engine ran zero pages /
        # zero candidates. Set by ``Downloader.search`` based on
        # whether the engine made any save attempt at all.
        self.no_results_found = no_results_found
        # ``cancelled`` is True if a CancelToken aborted the run.
        self.cancelled = cancelled
        # ``manifest_path`` is the absolute path to the JSONL
        # manifest file written by ``Downloader.search(manifest=True)``,
        # or ``None`` if no manifest was requested.
        self.manifest_path = manifest_path
        # ``_engine`` is set by ``Downloader.search()`` to expose the
        # underlying engine instance for advanced users. Always present
        # in real ``Downloader``-produced Results; ``None`` when a
        # Result is hand-constructed.
        self._engine: ImageEngine | None = None

    @property
    def count(self) -> int:
        """Number of newly-downloaded images (== ``len(self.images)``)."""
        return len(self.images)

    @property
    def total_bytes(self) -> int:
        """Sum of ``size_bytes`` across all images."""
        return sum(img.size_bytes for img in self.images)

    def engine_instance(self) -> ImageEngine | None:
        """Return the underlying :class:`ImageEngine` that produced this result.

        Returns ``None`` for hand-constructed :class:`Result` objects
        (e.g. in tests). For results produced by
        :meth:`Downloader.search`, this is the engine instance, useful
        for introspecting ``engine.download_count``, ``engine.manifest``,
        or any engine-specific attribute.

        Use this in preference to reading the private ``_engine``
        attribute directly.
        """
        return self._engine

    def __repr__(self) -> str:
        flags = []
        if self.no_results_found:
            flags.append("no_results_found")
        if self.cancelled:
            flags.append("cancelled")
        flag_str = f", flags={flags}" if flags else ""
        manifest_repr = self.manifest_path if self.manifest_path is not None else "no manifest"
        return (
            f"Result(query={self.query!r}, engine={self.engine!r}, "
            f"count={self.count}, skipped={self.skipped}, "
            f"errors={len(self.errors)}{flag_str}, "
            f"manifest_path={manifest_repr!r})"
        )
