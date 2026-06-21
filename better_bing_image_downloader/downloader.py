"""Embeddable :class:`Downloader` API (v3.2.0+).

The :class:`Downloader` is the recommended entry point for library users.
It owns:

- a session-shared ``http.cookiejar.CookieJar`` and
  ``urllib.request.OpenerDirector`` (so DuckDuckGo's vqd cookie, TLS
  handshake, and TCP connection can be reused across many search calls)
- a public engine registry — :meth:`Downloader.register` lets downstream
  code plug in custom engines without monkey-patching
- lifecycle hooks — ``on_image``, ``on_error``, ``on_engine_start``,
  ``on_engine_done`` — so a web service or notebook can show progress,
  log to its own system, or abort a run
- a :meth:`Downloader.search` method that returns a :class:`Result`
  object with the full list of saved images, errors, and metadata
- a JSONL manifest writer (v3.5.0+) — when ``manifest=True`` is passed
  to ``search()``, every attempt (success or failure) is appended to a
  ``manifest.jsonl`` file as the run progresses

The legacy module-level :func:`better_bing_image_downloader.downloader`
function is preserved as a thin wrapper around :class:`Downloader`.
"""

from __future__ import annotations

import http.cookiejar
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .base import DEFAULT_VERBOSE, ImageEngine
from .bing import Bing
from .duckduckgo import DuckDuckGo
from .manifest import DEFAULT_MANIFEST_FIELDS, ManifestWriter
from .results import ImageResult, Result

__all__ = [
    "Downloader",
    "ImageResult",
    "Result",
    "ImageSaveError",
    "NetworkError",
    "InvalidImageError",
    "DuplicateImageError",
    "WriteError",
    "CancelToken",
    "ManifestWriter",
    "DEFAULT_MANIFEST_FIELDS",
]


# Re-export the typed ImageSaveError subclasses from base.py so they
# remain accessible as ``better_bing_image_downloader.ImageSaveError``
# etc. The actual class definitions live in base.py to avoid a
# circular import (base.py -> downloader.py -> base.py).
from .base import (  # noqa: E402
    DuplicateImageError,
    ImageSaveError,
    InvalidImageError,
    NetworkError,
    WriteError,
)


class CancelToken:
    """A simple thread-safe one-shot cancellation flag.

    Pass an instance to :meth:`Downloader.search` via the ``cancel=``
    keyword argument; call :meth:`cancel` from another thread (or a
    signal handler) to abort the in-flight search. Engines that
    cooperate with the token (Bing, DuckDuckGo as of v3.3.0) will
    check it between page fetches and stop cleanly. The partial
    :class:`Result` is returned with ``result.cancelled = True``.

    Example
    -------

    >>> import threading
    >>> from better_bing_image_downloader import Downloader
    >>> from better_bing_image_downloader.downloader import CancelToken
    >>>
    >>> dl = Downloader()
    >>> token = CancelToken()
    >>>
    >>> def cancel_after(tok, delay):
    ...     import time
    ...     time.sleep(delay)
    ...     tok.cancel()
    >>>
    >>> threading.Thread(target=cancel_after, args=(token, 1.0)).start()
    >>> result = dl.search("red panda", limit=1000, engine="duckduckgo", cancel=token)
    >>> result.cancelled
    True
    """

    __slots__ = ("_cancelled", "_lock")

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        """``True`` once :meth:`cancel` has been called."""
        # Reading is racy without the lock, but the worst case is
        # the engine checks one iteration too many — which is fine.
        return self._cancelled

    def cancel(self) -> None:
        """Mark this token as cancelled. Idempotent."""
        with self._lock:
            self._cancelled = True

    def reset(self) -> None:
        """Reset the token so it can be reused for a new search."""
        with self._lock:
            self._cancelled = False

    def __repr__(self) -> str:
        return f"CancelToken(cancelled={self._cancelled})"


HookOnImage = Callable[[ImageResult], None]
HookOnError = Callable[[str, BaseException], None]
HookOnEngineStart = Callable[[str, str], None]  # (engine, query)
HookOnEngineDone = Callable[[str, Result], None]  # (engine, result)

# Progress hook signature: (percent, downloaded, total, eta_seconds).
# ``eta_seconds`` is None until we have at least one timing sample.
HookOnProgress = Callable[[float, int, int, float | None], None]


class Downloader:
    """Embeddable façade for image-search engines.

    A ``Downloader`` owns a session (cookie jar + opener), a registry of
    engines, and user-supplied lifecycle hooks. Use it for any
    non-trivial integration: looping over many queries, embedding in a
    web service, building a custom engine, or wiring in a UI.

    Examples
    --------
    Minimal one-liner:

    >>> from better_bing_image_downloader import Downloader
    >>> result = Downloader().search("red panda", limit=10)
    >>> print(result.count, "images saved to", result.output_dir)

    With hooks and a custom engine:

    >>> class MyEngine(Bing): ...
    >>> dl = Downloader(on_image=lambda img: print("saved", img.path))
    >>> dl.register("myengine", MyEngine)
    >>> result = dl.search("cat", engine="myengine", limit=5)
    """

    # Class-level default registry. Each instance gets its own copy
    # (see __init__), so per-instance ``register()`` calls don't leak
    # across Downloader() instances. Tests that want to swap the
    # registry can patch ``_DEFAULT_REGISTRY`` on the class.
    _DEFAULT_REGISTRY: dict[str, type[ImageEngine]] = {
        "bing": Bing,
        "duckduckgo": DuckDuckGo,
    }

    def __init__(
        self,
        cache_dir: Path | None = None,
        on_image: HookOnImage | None = None,
        on_error: HookOnError | None = None,
        on_engine_start: HookOnEngineStart | None = None,
        on_engine_done: HookOnEngineDone | None = None,
        on_progress: HookOnProgress | None = None,
    ) -> None:
        # --- Session: shared cookie jar + connection-pooled opener ---
        # The cookie jar is critical for DuckDuckGo: the vqd token is
        # tied to a session cookie, and reusing it across calls avoids
        # the 60+ KB /images redirect we would otherwise get on every
        # search.
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
        )

        self.cache_dir = Path(cache_dir) if cache_dir else None

        # --- Hooks ---
        self.on_image = on_image
        self.on_error = on_error
        self.on_engine_start = on_engine_start
        self.on_engine_done = on_engine_done
        self.on_progress = on_progress

        # --- Per-instance engine registry ---
        # Copy from the class default so per-instance ``register()``
        # calls don't leak to other Downloader instances, but tests can
        # still patch ``_DEFAULT_REGISTRY`` to swap the default set.
        self._registry: dict[str, type[ImageEngine]] = dict(self._DEFAULT_REGISTRY)
        self._registry_lock = threading.Lock()

        # --- Manifest writer (v3.5.0+). Set by ``search()``; ``None``
        # means no manifest is being written. The success/error hooks
        # inside ``search()`` read this attribute to decide whether to
        # append records.
        self._manifest_writer: ManifestWriter | None = None
        self._manifest_engine_name: str | None = None
        self._manifest_query: str | None = None

    # --- Engine registry ---

    def engines(self) -> list[str]:
        """Return the names of all currently registered engines."""
        with self._registry_lock:
            return sorted(self._registry.keys())

    def register(self, name: str, engine_cls: type[ImageEngine]) -> None:
        """Register a custom engine class under ``name``.

        Parameters
        ----------
        name : str
            Engine identifier. Must be unique; re-registering an
            existing name replaces the previous binding.
        engine_cls : type[ImageEngine]
            A subclass of :class:`ImageEngine`. Subclassing is
            enforced so the registry only accepts engines that
            implement the expected ``run()`` / ``download_image()``
            contract.

        Raises
        ------
        TypeError
            If ``engine_cls`` is not a subclass of :class:`ImageEngine`.
        ValueError
            If ``name`` is empty or contains whitespace.
        """
        if not isinstance(name, str) or not name or any(c.isspace() for c in name):
            raise ValueError(
                f"Engine name must be a non-empty string without whitespace, got {name!r}"
            )
        if not (isinstance(engine_cls, type) and issubclass(engine_cls, ImageEngine)):
            raise TypeError(f"Engine class must subclass ImageEngine, got {engine_cls!r}")
        with self._registry_lock:
            self._registry[name] = engine_cls

    def build_engine(
        self,
        engine_name: str,
        query: str,
        limit: int,
        output_dir: Path,
        **kwargs,
    ) -> ImageEngine:
        """Instantiate a registered engine by name.

        ``**kwargs`` is forwarded to the engine's ``__init__``. Each
        built-in engine accepts its own specific keyword arguments
        (``adult=``, ``safe_search=``, ``region=`` etc.); see the engine
        class docstrings.
        """
        with self._registry_lock:
            try:
                engine_cls = self._registry[engine_name]
            except KeyError:
                raise ValueError(
                    f"Unknown engine {engine_name!r}. " f"Registered: {sorted(self._registry)}"
                ) from None
        return engine_cls(query=query, limit=limit, output_dir=output_dir, **kwargs)

    # --- Search entry point ---

    def search(
        self,
        query: str,
        limit: int = 100,
        output_dir: str | Path = "dataset",
        engine: str = "bing",
        badsites: list[str] | None = None,
        name: str = "Image",
        max_workers: int = 4,
        force_replace: bool = False,
        timeout: int = 60,
        verbose: bool = DEFAULT_VERBOSE,
        image_filter: str = "",
        mkt: str = "en-US",
        ddg_safe_search: str = "moderate",
        ddg_region: str = "us-en",
        adult_filter_off: bool = False,
        cancel: CancelToken | None = None,
        manifest: bool = False,
        manifest_path: str | os.PathLike | None = None,
        manifest_fields: list[str] | None = None,
        manifest_flush_every: int = 1,
    ) -> Result:
        """Run a search and return a :class:`Result`.

        Parameters mirror the legacy module-level :func:`downloader`
        function; the only behavioural differences are the return type
        (``Result`` instead of ``int``) and that hooks are fired.

        Parameters
        ----------
        cancel : CancelToken | None
            Optional cancellation token. Pass an instance and call
            ``token.cancel()`` from another thread (or a signal
            handler) to abort the search. Cooperative engines
            (Bing, DuckDuckGo) check the token between page fetches
            and stop cleanly. The partial :class:`Result` is
            returned with ``result.cancelled = True``.
        manifest : bool
            If ``True``, write a JSONL ``manifest.jsonl`` file in
            ``output_dir`` (or at ``manifest_path``) with one record
            per attempted download (success or failure). The
            returned :class:`Result` exposes the absolute manifest
            path via ``result.manifest_path``; if ``manifest`` is
            ``False`` (the default), the field is ``None`` and no
            file is created. Default: ``False``.
        manifest_path : str | os.PathLike | None
            Override the manifest file path. If ``None`` (the
            default) and ``manifest=True``, the file is written to
            ``<output_dir>/<query>/manifest.jsonl``. Parent
            directories are created as needed.
        manifest_fields : list[str] | None
            Subset of manifest field names to include in each
            record. If ``None`` (the default), the full set of
            10 core+provenance fields is written. Unknown field
            names raise :class:`ManifestFieldError` at the start of
            the run.
        manifest_flush_every : int
            Flush the manifest file to disk every N records. The
            default ``1`` is crash-safe; higher values trade crash
            safety for throughput on slow disks. ``close()`` always
            flushes regardless of this value. Default: ``1``.
        """
        image_dir = Path(output_dir) / query
        image_dir.mkdir(parents=True, exist_ok=True)

        adult = "off" if adult_filter_off else "moderate"

        # --- Manifest writer (v3.5.0+) ---
        # Constructed here so it is open and ready to receive
        # records from the very first image attempt. Wrapped in
        # try/finally below to guarantee ``close()`` is called
        # even on exception. ``self._manifest_writer`` is also
        # set on the instance so the success/error hooks inside
        # ``_run_engine`` can append records to it.
        manifest_writer: ManifestWriter | None = None
        manifest_abs_path: str | None = None
        if manifest:
            resolved_manifest_path = (
                Path(manifest_path) if manifest_path else image_dir / "manifest.jsonl"
            )
            manifest_writer = ManifestWriter(
                resolved_manifest_path,
                fields=manifest_fields,
                flush_every=manifest_flush_every,
            )
            manifest_abs_path = str(resolved_manifest_path.resolve())
        # Expose to the success/error hooks below.
        self._manifest_writer = manifest_writer
        self._manifest_engine_name = engine
        self._manifest_query = query

        engine_kwargs: dict[str, object] = {}
        if engine == "bing":
            engine_kwargs = {
                "adult": adult,
                "filter": image_filter,
                "mkt": mkt,
            }
        elif engine == "duckduckgo":
            engine_kwargs = {
                "safe_search": ddg_safe_search,
                "region": ddg_region,
            }

        # Pass the cancel token to the engine so cooperative engines
        # (Bing, DuckDuckGo) can abort between page fetches.
        if cancel is not None:
            engine_kwargs["cancel"] = cancel

        engine_obj = self.build_engine(
            engine_name=engine,
            query=query,
            limit=limit,
            output_dir=image_dir,
            timeout=timeout,
            verbose=verbose,
            badsites=badsites or [],
            name=name,
            max_workers=max_workers,
            force_replace=force_replace,
            **engine_kwargs,
        )

        # Wire hooks: the engine records every successful save into
        # ``manifest`` and increments ``download_count`` / ``_slots_used``.
        # We tap the same counters to drive ``Result.images`` and fire
        # the user's ``on_image`` callback.
        if self.on_engine_start:
            try:
                self.on_engine_start(engine, query)
            except Exception:  # never let a user hook break the run
                logging.exception("on_engine_start hook raised; continuing")

        images: list[ImageResult] = []
        errors: list[tuple[str, BaseException]] = []
        seen_paths: set[Path] = set()
        # ``download_image_calls`` counts every time the engine
        # asked ``download_image`` to consider a candidate. We use
        # this to distinguish "no candidates fetched" from
        # "all candidates skipped" — both report ``_slots_used == 0``
        # but only the former means the search backend returned
        # nothing. (Resume-skip paths in download_image return
        # 0 before save_image is called, so save_attempts alone
        # would conflate the two cases.)
        download_image_calls = 0
        # ``save_attempts`` is the number of times save_image was
        # actually invoked (not skipped due to resume). Useful for
        # debugging.
        save_attempts = 0
        # ``progress_state`` tracks timing samples for ETA
        # computation. We need at least 2 samples (one for the
        # previous download, one for the current) to extrapolate.
        # ``_start_time`` is the time of the first sample,
        # ``_last_time`` is the time of the most recent sample,
        # ``_last_count`` is the ``download_count`` at the time of
        # the most recent sample.
        progress_state: dict[str, float | int] = {
            "_start_time": time.monotonic(),
            "_last_time": time.monotonic(),
            "_last_count": 0,
        }

        # Monkey-patch both save_image and download_image to count
        # calls and to capture every successful save and every error.
        # As of v3.4.0, we use ``_save_image_raising`` directly so
        # the wrapper receives typed ``ImageSaveError`` subclasses
        # (NetworkError, InvalidImageError, DuplicateImageError,
        # WriteError) instead of a generic ``False`` return.
        original_save_raising = engine_obj._save_image_raising
        original_download = engine_obj.download_image

        def save_with_hooks(link: str, file_path) -> bool:
            nonlocal save_attempts
            save_attempts += 1
            try:
                # ``_save_image_raising`` returns the MD5 hex digest
                # of the saved bytes (v3.5.0+). The legacy
                # ``save_image`` wrapper does not return it; we
                # rely on the raising variant here.
                file_md5 = original_save_raising(link, file_path)
            except ImageSaveError as exc:
                # Typed save failure (v3.4.0+). Surface via on_error
                # and Result.errors.
                errors.append((link, exc))
                if self.on_error:
                    try:
                        self.on_error(link, exc)
                    except Exception:
                        logging.exception("on_error hook raised; continuing")
                # Manifest append (v3.5.0+): record the typed failure.
                if self._manifest_writer is not None:
                    self._append_manifest_record(
                        status="error",
                        url=link,
                        file_path=None,
                        md5=None,
                        error=exc,
                        engine_obj=engine_obj,
                    )
                return False
            except Exception as exc:
                # Unhandled exception in save_image (e.g. a bug in
                # the engine subclass). Surface generically.
                errors.append((link, exc))
                if self.on_error:
                    try:
                        self.on_error(link, exc)
                    except Exception:
                        logging.exception("on_error hook raised; continuing")
                # Manifest append (v3.5.0+): record the unhandled failure.
                if self._manifest_writer is not None:
                    self._append_manifest_record(
                        status="error",
                        url=link,
                        file_path=None,
                        md5=None,
                        error=exc,
                        engine_obj=engine_obj,
                    )
                return False
            fp = Path(file_path)
            if fp in seen_paths:
                return True
            seen_paths.add(fp)
            try:
                size = fp.stat().st_size
            except OSError:
                size = 0
            # Re-detect mime by file extension since we already validated
            # via filetype during save_image.
            mime = _guess_mime(fp)
            ir = ImageResult(
                path=fp,
                source_url=link,
                engine=engine,
                query=query,
                image_index=engine_obj.download_count,  # set by save_image
                size_bytes=size,
                mime_type=mime,
            )
            images.append(ir)
            if self.on_image:
                try:
                    self.on_image(ir)
                except Exception:
                    logging.exception("on_image hook raised; continuing")
            # Fire the on_progress hook (v3.4.0+). The engine's
            # ``download_count`` is incremented inside
            # ``download_image`` *after* ``save_image`` returns,
            # so we add 1 to account for the image we just saved.
            if self.on_progress:
                done = engine_obj.download_count + 1
                total = limit
                pct = (done / total * 100.0) if total > 0 else 0.0
                eta = _compute_eta(progress_state, done, total)
                try:
                    self.on_progress(pct, done, total, eta)
                except Exception:
                    logging.exception("on_progress hook raised; continuing")
            # Manifest append (v3.5.0+): one record per successful save.
            if self._manifest_writer is not None:
                self._append_manifest_record(
                    status="ok",
                    url=link,
                    file_path=fp,
                    md5=file_md5,
                    error=None,
                    engine_obj=engine_obj,
                )
            return True

        # ``save_image`` is defined on the base ``ImageEngine`` class,
        # so this attribute assignment is legal Python but mypy flags
        # it. Suppress only the method-assign warning.
        engine_obj.save_image = save_with_hooks  # type: ignore[method-assign]

        def download_with_count(link: str, index: int):
            nonlocal download_image_calls
            download_image_calls += 1
            return original_download(link, index)

        # Wrap download_image to count how many candidates the engine
        # considered (including resume-skips).
        engine_obj.download_image = download_with_count  # type: ignore[method-assign]

        try:
            engine_obj.run()
        finally:
            # Always close the manifest writer, even on exception.
            # The writer is idempotent, so a second close (e.g. if
            # the search raises after a successful run) is a no-op.
            if manifest_writer is not None:
                manifest_writer.close()

        # Compute the run's high-level outcome flags.
        # ``no_results_found`` is True when the engine considered
        # zero candidate URLs. This distinguishes "the search
        # returned nothing" from "the search returned stuff but
        # it was all skipped or failed" — a distinction that was
        # invisible in 3.2.0 and earlier.
        no_results_found = download_image_calls == 0
        cancelled = cancel is not None and cancel.cancelled

        # ``skipped`` is clamped to zero: if a custom engine
        # incremented ``download_count`` without ``_slots_used`` (or
        # vice versa), the subtraction can go negative. We don't
        # want a nonsensical negative count in the result.
        skipped = max(0, engine_obj._slots_used - engine_obj.download_count)

        result = Result(
            query=query,
            engine=engine,
            output_dir=image_dir,
            images=images,
            skipped=skipped,
            errors=errors,
            no_results_found=no_results_found,
            cancelled=cancelled,
            manifest_path=manifest_abs_path,
        )
        # Attach the engine instance to the Result so the legacy
        # ``downloader()`` function can read ``engine.download_count``
        # for backwards compatibility.
        result._engine = engine_obj

        if self.on_engine_done:
            try:
                self.on_engine_done(engine, result)
            except Exception:
                logging.exception("on_engine_done hook raised; continuing")

        return result

    def _append_manifest_record(
        self,
        status: str,
        url: str,
        file_path: Path | None,
        md5: str | None,
        error: BaseException | None,
        engine_obj: ImageEngine,
    ) -> None:
        """Build a manifest record dict and append it to the writer.

        Called from the success and error paths inside :meth:`search`
        when ``manifest=True`` was passed. The record is filtered to
        the writer's configured fields automatically.

        ``file_path`` is stored relative to ``output_dir`` (i.e. as
        ``"<query>/Image_1.jpg"``) so the manifest is portable
        across machines. If the relative-to conversion fails (e.g.
        the engine wrote outside ``output_dir``), the basename is
        used as a fallback.
        """
        if self._manifest_writer is None:
            return
        # ``index`` is 1-based and counts every record (success or
        # failure). The engine's ``download_count`` is incremented
        # inside ``download_image`` *after* ``save_image`` returns,
        # so at the point we append to the manifest, the success
        # path's count reflects this image and the failure path's
        # count does not (the engine did not advance). We add 1 in
        # the success path to make the index 1-based; the failure
        # path's count is already the right 0-based position, but
        # we also add 1 for consistency.
        index = engine_obj.download_count + 1
        # Resolve file path relative to output_dir.
        file_rel: str | None = None
        if file_path is not None:
            try:
                file_rel = str(file_path.resolve().relative_to(Path.cwd()))
            except ValueError:
                file_rel = file_path.name
        self._manifest_writer.append(
            {
                "index": index,
                "status": status,
                "url": url,
                "file": file_rel,
                "md5": md5,
                "error": type(error).__name__ if error is not None else None,
                "engine": self._manifest_engine_name,
                "query": self._manifest_query,
                "source_page": getattr(engine_obj, "last_page_url", None),
                "downloaded_at": _utcnow_iso(),
            }
        )

    async def search_async(
        self,
        query: str,
        limit: int = 100,
        output_dir: str | Path = "dataset",
        engine: str = "bing",
        badsites: list[str] | None = None,
        name: str = "Image",
        max_workers: int = 4,
        force_replace: bool = False,
        timeout: int = 60,
        verbose: bool = DEFAULT_VERBOSE,
        image_filter: str = "",
        mkt: str = "en-US",
        ddg_safe_search: str = "moderate",
        ddg_region: str = "us-en",
        adult_filter_off: bool = False,
        cancel: CancelToken | None = None,
        manifest: bool = False,
        manifest_path: str | os.PathLike | None = None,
        manifest_fields: list[str] | None = None,
        manifest_flush_every: int = 1,
    ) -> Result:
        """Async wrapper around :meth:`search`.

        Runs the (blocking) ``search()`` in a worker thread via
        :func:`asyncio.to_thread`, so it works with the stdlib-only
        urllib-based engines without requiring an event loop on
        the engine side. Returns the same :class:`Result`.

        Use this in async code (FastAPI, aiohttp, Jupyter with
        ``top-level await``) so a long search doesn't block the
        event loop.

        Example
        -------
        >>> import asyncio
        >>> from better_bing_image_downloader import Downloader
        >>>
        >>> async def main():
        ...     dl = Downloader()
        ...     result = await dl.search_async("red panda", limit=10)
        ...     print(result.count)
        >>>
        >>> asyncio.run(main())
        """
        import asyncio

        # ``asyncio.to_thread`` is the right call here:
        # - it doesn't require the function to be a coroutine
        # - it gives back the GIL so the event loop can serve
        #   other tasks while the search runs
        # - it works in any context (no global executor needed)
        return await asyncio.to_thread(
            self.search,
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
            cancel=cancel,
            manifest=manifest,
            manifest_path=manifest_path,
            manifest_fields=manifest_fields,
            manifest_flush_every=manifest_flush_every,
        )


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with a trailing 'Z'.

    Used by the manifest writer to stamp each record's
    ``downloaded_at`` field. Format: ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_eta(state: dict[str, float | int], done: int, total: int) -> float | None:
    """Estimate seconds remaining based on timing samples.

    Returns ``None`` until we have at least 2 samples (the first
    download can't be extrapolated — we don't know the rate yet).
    On the first call, the state ``_last_count`` is 0; if the
    new ``done`` is also 0, we have no signal at all. Once we've
    seen at least one completed download, subsequent calls
    extrapolate based on the rate of progress.
    """
    now = time.monotonic()
    last_time = float(state["_last_time"])
    last_count = int(state["_last_count"])
    is_first_call = last_count == 0 and state.get("_initialized", False) is False
    if is_first_call:
        # First call: we don't have a rate yet. Just record the
        # state for the next call.
        state["_last_time"] = now
        state["_last_count"] = done
        state["_initialized"] = True
        return None
    if done == last_count:
        return None
    elapsed = now - last_time
    if elapsed <= 0:
        return None
    rate = (done - last_count) / elapsed
    remaining = total - done
    if rate <= 0 or remaining <= 0:
        return None
    state["_last_time"] = now
    state["_last_count"] = done
    return remaining / rate


def _guess_mime(path: Path) -> str:
    """Return a best-effort MIME type from the file extension."""
    import mimetypes

    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"
