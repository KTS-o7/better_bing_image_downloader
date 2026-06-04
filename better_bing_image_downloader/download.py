"""Public downloader API and CLI entry point."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import warnings
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

from tqdm import tqdm

from .bing import Bing

__all__ = ["downloader", "main"]


def _build_engine(engine, query, limit, output_dir, image_filter, timeout, verbose,
                  badsites, name, max_workers, force_replace, adult,
                  ddg_safe_search, ddg_region, mkt):
    """Instantiate the requested engine.

    Raises
    ------
    ValueError
        If ``engine`` is not a known engine name.
    ImportError
        If the DuckDuckGo engine is requested but ``brotli`` is missing.
    """
    if engine == "bing":
        return Bing(
            query=query,
            limit=limit,
            output_dir=output_dir,
            adult=adult,
            timeout=timeout,
            filter=image_filter,
            verbose=verbose,
            badsites=badsites,
            name=name,
            max_workers=max_workers,
            force_replace=force_replace,
            mkt=mkt,
        )
    if engine == "duckduckgo":
        # Imported lazily so the Bing path doesn't require brotli.
        from .duckduckgo import DuckDuckGo
        return DuckDuckGo(
            query=query,
            limit=limit,
            output_dir=output_dir,
            timeout=timeout,
            verbose=verbose,
            badsites=badsites,
            name=name,
            max_workers=max_workers,
            force_replace=force_replace,
            safe_search=ddg_safe_search,
            region=ddg_region,
        )
    raise ValueError(
        f"Unknown engine {engine!r}. Must be 'bing' or 'duckduckgo'."
    )


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
    **kwargs,
) -> int:
    """Download images matching ``query`` using the chosen search engine.

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

    if engine not in ("bing", "duckduckgo"):
        raise ValueError(
            f"engine must be 'bing' or 'duckduckgo', got {engine!r}"
        )

    # Bing-specific options silently ignored when using DuckDuckGo
    if engine == "duckduckgo" and verbose:
        for ignored in ("mkt", "image_filter", "adult_filter_off"):
            pass  # silently ignore, no warning for now

    # Set adult filter setting (Bing only)
    adult = "off" if adult_filter_off else "moderate"

    badsites = list(badsites) if badsites else []

    image_dir = Path(output_dir) / query

    if force_replace and image_dir.exists():
        shutil.rmtree(image_dir)

    try:
        image_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f"Failed to create directory {image_dir}: {e}") from e

    logging.info("Downloading Images to %s", image_dir)

    with tqdm(
        total=limit, unit="img", ncols=100, colour="green",
        bar_format=(
            "{l_bar}{bar} {n_fmt}/{total_fmt} imgs "
            "| Speed: {rate_fmt} | ETA: {remaining}"
        ),
    ) as pbar:
        def update_progress_bar(download_count: int) -> None:
            pbar.n = download_count
            pbar.refresh()

        engine_obj = _build_engine(
            engine=engine,
            query=query,
            limit=limit,
            output_dir=image_dir,
            image_filter=image_filter,
            timeout=timeout,
            verbose=verbose,
            badsites=badsites,
            name=name,
            max_workers=max_workers,
            force_replace=force_replace,
            adult=adult,
            ddg_safe_search=ddg_safe_search,
            ddg_region=ddg_region,
            mkt=mkt,
        )
        engine_obj.download_callback = update_progress_bar  # type: ignore[attr-defined]
        try:
            engine_obj.run()
        finally:
            manifest_path = image_dir / "_manifest.json"
            existing_manifest = {}
            if manifest_path.exists():
                try:
                    with open(manifest_path) as f:
                        existing_manifest = json.load(f)
                except Exception:
                    pass
            existing_manifest.update(engine_obj.manifest)
            try:
                with open(manifest_path, "w") as f:
                    json.dump(existing_manifest, f, indent=2)
            except Exception as e:
                logging.error("Failed to write manifest: %s", e)

    return engine_obj.download_count


def main() -> None:
    """Entry point for the ``bbid`` CLI command."""
    parser = argparse.ArgumentParser(
        description="Download images using Bing or DuckDuckGo."
    )
    try:
        _version = pkg_version("better-bing-image-downloader")
    except PackageNotFoundError:
        _version = "unknown"
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version}")
    parser.add_argument("query", type=str, help="The search query.")
    parser.add_argument("-l", "--limit", type=int, default=100,
                        help="The maximum number of images to download.")
    parser.add_argument("-d", "--output_dir", type=str, default="dataset",
                        help="The directory to save the images in.")
    parser.add_argument("-a", "--adult_filter_off", action="store_true",
                        help="Turn off the adult filter (Bing only).")
    parser.add_argument("-F", "--force_replace", action="store_true",
                        help="Re-download and replace existing files.")
    parser.add_argument("-t", "--timeout", type=int, default=60,
                        help="Per-request timeout in seconds.")
    parser.add_argument("-f", "--filter", type=str, default="", dest="image_filter",
                        help="Bing image-type filter (photo, clipart, line, gif, transparent).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print detailed output.")
    parser.add_argument("-b", "--bad-sites", nargs="*", default=[],
                        help="Hostnames to exclude from results.")
    parser.add_argument("-n", "--name", type=str, default="Image",
                        help="Base name for downloaded images.")
    parser.add_argument("-w", "--workers", type=int, default=4,
                        help="Maximum number of parallel download workers.")
    parser.add_argument("-m", "--mkt", type=str, default="en-US",
                        help="Bing market code (e.g. en-US, de-DE). Bing only.")
    parser.add_argument("-e", "--engine", type=str, default="bing",
                        choices=["bing", "duckduckgo"],
                        help="Search engine to use (default: bing).")
    parser.add_argument("--ddg-safe-search", type=str, default="moderate",
                        choices=["strict", "moderate", "off"],
                        help="DuckDuckGo safe-search mode (default: moderate).")
    parser.add_argument("--ddg-region", type=str, default="us-en",
                        help="DuckDuckGo region code (default: us-en).")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

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
    )


if __name__ == "__main__":
    main()
