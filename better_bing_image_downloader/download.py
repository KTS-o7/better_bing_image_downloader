"""Legacy ``downloader()`` function and the ``bbid`` CLI entry point.

The module-level :func:`downloader` is preserved as a thin wrapper
around :class:`better_bing_image_downloader.downloader.Downloader`
for backwards compatibility with code written against the v3.0.x and
v3.1.x API.

New code should prefer :class:`Downloader` directly: it gives you a
:class:`Result` object, lifecycle hooks, and the engine registry.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import warnings
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

from tqdm import tqdm

from .downloader import Downloader

__all__ = ["downloader", "main"]


def downloader(
    query: str,
    limit: int = 100,
    output_dir: str = "dataset",
    adult_filter_off: bool = False,
    force_replace: bool = False,
    timeout: int = 60,
    image_filter: str = "",
    verbose: bool = True,
    badsites: list | None = None,
    name: str = "Image",
    max_workers: int = 4,
    mkt: str = "en-US",
    engine: str = "bing",
    ddg_safe_search: str = "moderate",
    ddg_region: str = "us-en",
    manifest: bool = False,
    manifest_path: str | None = None,
    manifest_fields: list[str] | None = None,
    manifest_flush_every: int = 1,
    min_dimension: int | None = None,
    **kwargs,
) -> int:
    """Download images matching ``query`` using the chosen search engine.

    .. deprecated:: 3.2.0
        This function is kept for backwards compatibility. New code
        should use :class:`Downloader` directly to get a
        :class:`Result` object, lifecycle hooks, and engine registry
        support. The function will not be removed.

    Parameters
    ----------
    query : str
        Search query.
    limit : int
        Maximum number of images to download.
    output_dir : str
        Directory to save images in. Images are saved under
        ``output_dir / query``.
    adult_filter_off : bool
        If ``True``, disables adult-content filtering (Bing only).
    force_replace : bool
        Re-download images even if they already exist.
    timeout : int
        Per-request timeout in seconds.
    image_filter : str
        Bing image-type filter (``"photo"``, ``"clipart"``, etc.).
    verbose : bool
        Print progress information.
    badsites : list[str] | None
        Hostnames to exclude from results.
    name : str
        Base filename for downloaded images.
    max_workers : int
        Number of parallel download workers.
    mkt : str
        Bing market code (Bing only).
    engine : str
        Search engine to use: ``"bing"`` (default) or ``"duckduckgo"``.
    ddg_safe_search : str
        DuckDuckGo safe-search mode: ``"strict"``, ``"moderate"``,
        or ``"off"``. Default ``"moderate"``.
    ddg_region : str
        DuckDuckGo region code (e.g. ``"us-en"``). Default ``"us-en"``.
    min_dimension : int | None
        Minimum width/height in pixels (v3.6.0+). Images smaller than
        this on either side are skipped. ``None`` (the default)
        disables the filter.

    Returns
    -------
    int
        Number of images newly downloaded by this call. Does not count
        files that were already on disk from a previous run.
    """
    # Backward compatibility: accept old 'filter' keyword arg
    if "filter" in kwargs:
        warnings.warn(
            "The 'filter' parameter is deprecated, use 'image_filter' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        image_filter = kwargs.pop("filter")

    if kwargs:
        raise TypeError(f"Unexpected keyword arguments: {sorted(kwargs)}")

    if engine not in ("bing", "duckduckgo"):
        raise ValueError(f"engine must be 'bing' or 'duckduckgo', got {engine!r}")

    badsites = list(badsites) if badsites else []

    # Honour the legacy progress-bar behaviour: the v3.1.x downloader()
    # function showed a tqdm bar. The new Downloader() doesn't (it
    # surfaces progress via hooks instead). We bridge that here.
    image_dir = Path(output_dir) / query
    if force_replace and image_dir.exists():
        shutil.rmtree(image_dir)

    logging.info("Downloading Images to %s", image_dir)

    dl = Downloader()
    pbar_cm = None
    if verbose:
        pbar_cm = tqdm(
            total=limit,
            unit="img",
            ncols=100,
            colour="green",
            bar_format=(
                "{l_bar}{bar} {n_fmt}/{total_fmt} imgs " "| Speed: {rate_fmt} | ETA: {remaining}"
            ),
        )

    def _on_image(_img) -> None:
        if pbar_cm is not None:
            pbar_cm.n = _on_image.counter  # type: ignore[attr-defined]
            pbar_cm.refresh()
        _on_image.counter = getattr(_on_image, "counter", 0) + 1  # type: ignore[attr-defined]

    dl.on_image = _on_image

    try:
        result = dl.search(
            query=query,
            limit=limit,
            output_dir=output_dir,
            engine=engine,
            badsites=badsites,
            name=name,
            max_workers=max_workers,
            force_replace=force_replace,
            timeout=timeout,
            verbose=verbose,
            image_filter=image_filter,
            mkt=mkt,
            ddg_safe_search=ddg_safe_search,
            ddg_region=ddg_region,
            adult_filter_off=adult_filter_off,
            manifest=manifest,
            manifest_path=manifest_path,
            manifest_fields=manifest_fields,
            manifest_flush_every=manifest_flush_every,
            min_dimension=min_dimension,
        )
        # Preserve the v3.1.x contract: the legacy downloader()
        # function returns the engine's ``download_count``, which the
        # engine controls. The new ``Downloader().search()`` returns a
        # ``Result`` whose ``.count`` is the hook-observed save count.
        # These should be equal in real runs (every save the engine
        # counts also fires the on_image hook), but the legacy API
        # exposes the engine's view for backwards compatibility.
        eng = result.engine_instance()
        # Surface the manifest path (v3.5.0+) so users can find the
        # JSONL file from a CLI run. Mirrors the v3.1.x _manifest.json
        # behaviour but in the new format.
        if getattr(result, "manifest_path", None):
            logging.info("Wrote manifest to %s", result.manifest_path)
        if eng is not None:
            return eng.download_count
        return result.count
    finally:
        if pbar_cm is not None:
            pbar_cm.close()
        # v3.1.x also wrote a _manifest.json file at the end. We
        # preserve that for any tooling that depends on it.
        _write_legacy_manifest(image_dir, result if "result" in locals() else None)


def _write_legacy_manifest(image_dir: Path, result) -> None:
    """Write the v3.1.x-style _manifest.json. Best-effort, never raises."""
    try:
        existing: dict = {}
        manifest_path = image_dir / "_manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    existing = json.load(f)
            except Exception:
                pass
        if result is not None:
            # Include both the engine's view (filename -> source_url,
            # preserved from v3.1.x) and the Result's view (from the
            # hook-observed save events). They are usually identical,
            # but merging keeps the legacy contract intact.
            engine = getattr(result, "_engine", None)
            if engine is not None and getattr(engine, "manifest", None):
                existing.update(engine.manifest)
            for img in result.images:
                existing[img.path.name] = img.source_url
        with open(manifest_path, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        logging.error("Failed to write manifest: %s", e)


def main() -> None:
    """Entry point for the ``bbid`` CLI command."""
    parser = argparse.ArgumentParser(description="Download images using Bing or DuckDuckGo.")
    try:
        _version = pkg_version("better-bing-image-downloader")
    except PackageNotFoundError:
        _version = "unknown"
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version}")
    parser.add_argument("query", type=str, help="The search query.")
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=100,
        help="The maximum number of images to download.",
    )
    parser.add_argument(
        "-d",
        "--output_dir",
        type=str,
        default="dataset",
        help="The directory to save the images in.",
    )
    parser.add_argument(
        "-a",
        "--adult_filter_off",
        action="store_true",
        help="Turn off the adult filter (Bing only).",
    )
    parser.add_argument(
        "-F",
        "--force_replace",
        action="store_true",
        help="Re-download and replace existing files.",
    )
    parser.add_argument(
        "-t", "--timeout", type=int, default=60, help="Per-request timeout in seconds."
    )
    parser.add_argument(
        "-f",
        "--filter",
        type=str,
        default="",
        dest="image_filter",
        help="Bing image-type filter (photo, clipart, line, gif, transparent).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed output.")
    parser.add_argument(
        "-b",
        "--bad-sites",
        nargs="*",
        default=[],
        help="Hostnames to exclude from results.",
    )
    parser.add_argument(
        "-n",
        "--name",
        type=str,
        default="Image",
        help="Base name for downloaded images.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Maximum number of parallel download workers.",
    )
    parser.add_argument(
        "-m",
        "--mkt",
        type=str,
        default="en-US",
        help="Bing market code (e.g. en-US, de-DE). Bing only.",
    )
    parser.add_argument(
        "-e",
        "--engine",
        type=str,
        default="bing",
        choices=["bing", "duckduckgo"],
        help="Search engine to use (default: bing).",
    )
    parser.add_argument(
        "--ddg-safe-search",
        type=str,
        default="moderate",
        choices=["strict", "moderate", "off"],
        help="DuckDuckGo safe-search mode (default: moderate).",
    )
    parser.add_argument(
        "--ddg-region",
        type=str,
        default="us-en",
        help="DuckDuckGo region code (default: us-en).",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Write a JSONL manifest.jsonl with one record per download attempt.",
    )
    parser.add_argument(
        "--manifest-path",
        type=str,
        default=None,
        help="Override the manifest output path (default: <output_dir>/<query>/manifest.jsonl).",
    )
    parser.add_argument(
        "--manifest-fields",
        type=str,
        default=None,
        help=(
            "Comma-separated list of manifest fields to include. "
            "Valid: index,status,url,file,md5,error,engine,query,source_page,downloaded_at. "
            "Default: all fields."
        ),
    )
    parser.add_argument(
        "--manifest-flush-every",
        type=int,
        default=1,
        help="Flush the manifest file to disk every N records (default: 1, crash-safe).",
    )
    parser.add_argument(
        "--min-dimension",
        type=int,
        default=None,
        help="Minimum width/height in pixels; smaller images are skipped (default: no filtering).",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    manifest_fields_list = None
    if args.manifest_fields:
        manifest_fields_list = [f.strip() for f in args.manifest_fields.split(",") if f.strip()]

    downloader(
        args.query,
        args.limit,
        args.output_dir,
        args.adult_filter_off,
        args.force_replace,
        args.timeout,
        args.image_filter,
        args.verbose,
        args.bad_sites,
        args.name,
        args.workers,
        args.mkt,
        engine=args.engine,
        ddg_safe_search=args.ddg_safe_search,
        ddg_region=args.ddg_region,
        manifest=args.manifest,
        manifest_path=args.manifest_path,
        manifest_fields=manifest_fields_list,
        manifest_flush_every=args.manifest_flush_every,
        min_dimension=args.min_dimension,
    )


if __name__ == "__main__":
    main()
