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
import warnings
from pathlib import Path
from typing import Callable, Optional

from .base import DEFAULT_VERBOSE, ImageEngine
from .bing import Bing
from .cancel import CancelToken
from .duckduckgo import DuckDuckGo
from .manifest import (
    DEFAULT_MANIFEST_FIELDS,
    ManifestWriter,
    _append_manifest_record,
    _ManifestContext,
)
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
    "BelowMinDimension",
    "CancelToken",
    "ManifestWriter",
    "DEFAULT_MANIFEST_FIELDS",
]


# Re-export the typed ImageSaveError subclasses from base.py so they
# remain accessible as ``better_bing_image_downloader.ImageSaveError``
# etc. The actual class definitions live in base.py to avoid a
# circular import (base.py -> downloader.py -> base.py).
from .base import (  # noqa: E402
    BelowMinDimension,
    DuplicateImageError,
    ImageSaveError,
    InvalidImageError,
    NetworkError,
    WriteError,
)

HookOnImage = Callable[[ImageResult], None]
HookOnError = Callable[[str, BaseException], None]
HookOnEngineStart = Callable[[str, str], None]  # (engine, query)
HookOnEngineDone = Callable[[str, Result], None]  # (engine, result)

# Progress hook signature: (percent, downloaded, total, eta_seconds).
# ``eta_seconds`` is None until we have at least one timing sample.
# Written as ``Optional[float]`` rather than ``float | None`` because
# this is a module-level expression (not a forward-reference annotation
# governed by ``from __future__ import annotations``), and the PEP 604
# ``X | Y`` union syntax only evaluates at runtime on Python 3.10+.
HookOnProgress = Callable[[float, int, int, Optional[float]], None]


def _fire_hook(hook, *args) -> None:
    """Invoke a user hook without ever letting it break the run."""
    if hook is not None:
        try:
            hook(*args)
        except Exception:
            logging.exception("hook raised; continuing")


class _SearchSession:
    """Per-search mutable state and engine hook wiring for one ``search()`` call.

    Extracted from ``Downloader.search`` so the method stays an
    orchestration outline. One instance lives exactly as long as one
    ``search()`` invocation: it owns the result lists, counters, and
    the monkey-patched ``save_image``/``download_image`` wrappers, then
    builds the final :class:`Result`.
    """

    def __init__(
        self,
        downloader: Downloader,
        engine_obj: ImageEngine,
        engine: str,
        query: str,
        limit: int,
        manifest_ctx: _ManifestContext | None,
    ) -> None:
        self._dl = downloader
        self._engine_obj = engine_obj
        self._engine = engine
        self._query = query
        self._limit = limit
        self._manifest_ctx = manifest_ctx
        self.images: list[ImageResult] = []
        self.errors: list[tuple[str, BaseException]] = []
        self._seen_paths: set[Path] = set()
        # Counts every candidate the engine considered (including
        # resume-skips), distinguishing "backend returned nothing"
        # from "everything was skipped or failed".
        self.download_image_calls = 0
        self.save_attempts = 0
        # Too-small images are an intentional filter outcome, not a
        # failure, so they get their own counter for Result.skipped.
        self.min_dimension_skips = 0
        self._progress_state: dict[str, float | int] = {
            "_start_time": time.monotonic(),
            "_last_time": time.monotonic(),
            "_last_count": 0,
        }

    def install(self) -> None:
        """Wire this session as the engine's save-event collector.

        Replaces the pre-4.1.0 monkey-patching of ``save_image`` /
        ``download_image``: the base ``download_image`` pipeline calls
        back into ``note_candidate`` / ``save_with_hooks`` explicitly.
        """
        self._engine_obj.collector = self

    def uninstall(self) -> None:
        """Detach from the engine so no session outlives its run."""
        self._engine_obj.collector = None

    def note_candidate(self) -> None:
        """Record one considered candidate URL (including resume-skips)."""
        self.download_image_calls += 1

    def save_with_hooks(self, link: str, file_path) -> bool:
        """Save one image, recording success/skip/error and firing hooks."""
        self.save_attempts += 1
        try:
            # ``_save_image_raising`` returns the MD5 hex digest of the
            # saved bytes; the legacy wrapper does not, hence the
            # raising variant here.
            file_md5 = self._engine_obj._save_image_raising(link, file_path)
        except BelowMinDimension as exc:
            return self._record_skip(link, exc)
        except (ImageSaveError, Exception) as exc:
            return self._record_error(link, exc)
        return self._record_success(link, file_path, file_md5)

    def _manifest_append(self, status: str, url: str, file_path, md5, error) -> None:
        if self._manifest_ctx is not None:
            _append_manifest_record(
                self._manifest_ctx,
                status=status,
                url=url,
                file_path=file_path,
                md5=md5,
                error=error,
                engine_obj=self._engine_obj,
            )

    def _record_skip(self, link: str, exc: BaseException) -> bool:
        self.min_dimension_skips += 1
        self._manifest_append("skipped", link, None, None, exc)
        return False

    def _record_error(self, link: str, exc: BaseException) -> bool:
        self.errors.append((link, exc))
        _fire_hook(self._dl.on_error, link, exc)
        self._manifest_append("error", link, None, None, exc)
        return False

    def _record_success(self, link: str, file_path, file_md5: str) -> bool:
        fp = Path(file_path)
        if fp in self._seen_paths:
            return True
        self._seen_paths.add(fp)
        ir = self._make_image_result(link, fp)
        self.images.append(ir)
        _fire_hook(self._dl.on_image, ir)
        self._fire_progress()
        self._manifest_append("ok", link, fp, file_md5, None)
        return True

    @staticmethod
    def _file_size(fp: Path) -> int:
        try:
            return fp.stat().st_size
        except OSError:
            return 0

    def _make_image_result(self, link: str, fp: Path) -> ImageResult:
        """Build the value object for a freshly saved file (no side effects)."""
        return ImageResult(
            path=fp,
            source_url=link,
            engine=self._engine,
            query=self._query,
            image_index=self._engine_obj.download_count,  # set by save_image
            size_bytes=self._file_size(fp),
            mime_type=_guess_mime(fp),  # extension-based; content validated on save
            caption=getattr(self._engine_obj, "captions", {}).get(link),
        )

    def _fire_progress(self) -> None:
        if self._dl.on_progress is None:
            return
        # ``download_count`` is incremented inside ``download_image``
        # *after* ``save_image`` returns, so add 1 for the image just saved.
        done = self._engine_obj.download_count + 1
        total = self._limit
        pct = (done / total * 100.0) if total > 0 else 0.0
        eta = _compute_eta(self._progress_state, done, total)
        _fire_hook(self._dl.on_progress, pct, done, total, eta)

    def build_result(
        self,
        image_dir: Path,
        manifest_abs_path: str | None,
        cancel: CancelToken | None,
    ) -> Result:
        """Assemble the final :class:`Result` and fire ``on_engine_done``."""
        skipped = (
            max(0, self._engine_obj._slots_used - self._engine_obj.download_count)
            + self.min_dimension_skips
        )
        result = Result(
            query=self._query,
            engine=self._engine,
            output_dir=image_dir,
            images=self.images,
            skipped=skipped,
            errors=self.errors,
            no_results_found=self.download_image_calls == 0,
            cancelled=cancel is not None and cancel.cancelled,
            manifest_path=manifest_abs_path,
        )
        # Expose the engine for the legacy ``downloader()`` contract.
        result._engine = self._engine_obj
        _fire_hook(self._dl.on_engine_done, self._engine, result)
        return result


class Downloader:
    """Embeddable façade for image-search engines.

    A ``Downloader`` owns a session (cookie jar + opener), a registry of
    engines, and user-supplied lifecycle hooks. Use it for any
    non-trivial integration: looping over many queries, embedding in a
    web service, building a custom engine, or wiring in a UI.

    Parameters
    ----------
    cache_dir : Path | None
        Optional directory to cache downloaded images in.
    on_image, on_error, on_engine_start, on_engine_done, on_progress :
        Optional lifecycle hooks, see ``HookOn*`` type aliases.
    proxy : str | None
        Optional HTTP/HTTPS proxy URL (e.g. ``"http://proxy:8080"``).
        When set, every request this Downloader makes — search page
        fetches and image downloads — is routed through the proxy via a
        ``urllib.request.ProxyHandler``. With ``None`` (default),
        requests behave exactly as before and honour the standard
        ``HTTP_PROXY``/``HTTPS_PROXY`` environment variables.

    Thread safety
    -------------
    A ``Downloader`` instance may be shared across threads **only when
    every ``search()`` call uses ``manifest=False``** (the default):
    after construction, ``search()`` is read-only with respect to the
    engine registry and the cookie jar is only used through per-request
    opener state.

    When ``manifest=True`` the instance is **not safe to share across
    threads** — the underlying ``ManifestWriter`` is single-threaded,
    and concurrent ``search(manifest=True)`` calls on the same instance
    can interleave or corrupt ``manifest.jsonl`` records. Use one
    ``Downloader`` per thread in that case.

    ``CancelToken`` is thread-safe and can be shared freely: call
    ``cancel()`` from any thread to abort a running ``search()``.

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
        proxy: str | None = None,
    ) -> None:
        # --- Session: shared cookie jar + connection-pooled opener ---
        # The cookie jar is critical for DuckDuckGo: the vqd token is
        # tied to a session cookie, and reusing it across calls avoids
        # the 60+ KB /images redirect we would otherwise get on every
        # search.
        self.proxy = proxy
        self.cookie_jar = http.cookiejar.CookieJar()
        opener_handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        ]
        if proxy:
            opener_handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*opener_handlers)

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

        # Manifest state (v3.5.0+) is deliberately NOT kept on the
        # instance: each ``search()`` call builds its own invocation-
        # local :class:`_ManifestContext` so nested or concurrent
        # searches on the same ``Downloader`` never clobber each
        # other's writer, metadata, or record counter.

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

    @staticmethod
    def _open_manifest(
        image_dir: Path,
        engine: str,
        query: str,
        manifest: bool,
        manifest_path: str | os.PathLike | None,
        manifest_fields: list[str] | None,
        manifest_flush_every: int,
    ) -> tuple[ManifestWriter | None, _ManifestContext | None, str | None]:
        """Create the manifest writer triple, or all-``None`` when disabled.

        The writer is opened up front so it can receive records from the
        very first image attempt; the caller must ``close()`` it in a
        ``finally``. State is invocation-local (never on ``self``) so
        nested or concurrent ``search()`` calls never share a writer.
        """
        if not manifest:
            return None, None, None
        resolved = Path(manifest_path) if manifest_path else image_dir / "manifest.jsonl"
        writer = ManifestWriter(
            resolved,
            fields=manifest_fields,
            flush_every=manifest_flush_every,
        )
        return writer, _ManifestContext(writer, engine, query), str(resolved.resolve())

    def _engine_kwargs_for(
        self,
        engine: str,
        adult: str,
        image_filter: str,
        mkt: str,
        license: str,
        ddg_safe_search: str,
        ddg_region: str,
        adult_filter_off: bool,
        cancel: CancelToken | None,
        min_dimension: int | None,
    ) -> dict[str, object]:
        """Assemble engine constructor kwargs, warning on ignored options."""
        kwargs: dict[str, object] = {}
        if engine == "bing":
            kwargs = {
                "adult": adult,
                "filter": image_filter,
                "mkt": mkt,
                "license": license,
            }
        elif engine == "duckduckgo":
            kwargs = {
                "safe_search": ddg_safe_search,
                "region": ddg_region,
            }
            # Bing-only options are silently ignored by DuckDuckGo — warn
            # instead of dropping them quietly (#78). Custom engines fall
            # through untouched.
            for key, value, default in (
                ("image_filter", image_filter, ""),
                ("mkt", mkt, "en-US"),
                ("license", license, "any"),
                ("adult_filter_off", adult_filter_off, False),
            ):
                if value != default:
                    warnings.warn(
                        f"{key}={value!r} is Bing-only and ignored " 'with engine="duckduckgo".',
                        UserWarning,
                        # warn() <- _engine_kwargs_for <- search <-
                        # user code: point at the search() call site.
                        stacklevel=3,
                    )
        # Optional keys are only added when used, so engines that don't
        # accept them (e.g. third-party ones ignoring a feature) are
        # unaffected.
        if cancel is not None:
            kwargs["cancel"] = cancel
        if min_dimension is not None:
            kwargs["min_dimension"] = min_dimension
        if self.proxy is not None:
            kwargs["proxy"] = self.proxy
        return kwargs

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
        min_dimension: int | None = None,
        license: str = "any",
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
        min_dimension : int | None
            Minimum width and height in pixels (v3.6.0+). If set, any
            downloaded image smaller than this on either side is
            skipped: it does not count toward :attr:`Result.images`
            or :attr:`Result.errors`, is recorded in the manifest (if
            ``manifest=True``) as ``status="skipped"``,
            ``error="BelowMinDimension"``, and is counted in
            :attr:`Result.skipped`. Images in formats we can't
            measure (e.g. TIFF) are not filtered. Default ``None``
            (no filtering).
        """
        image_dir = Path(output_dir) / query
        image_dir.mkdir(parents=True, exist_ok=True)

        adult = "off" if adult_filter_off else "moderate"

        manifest_writer, manifest_ctx, manifest_abs_path = self._open_manifest(
            image_dir,
            engine,
            query,
            manifest,
            manifest_path,
            manifest_fields,
            manifest_flush_every,
        )

        engine_kwargs = self._engine_kwargs_for(
            engine,
            adult,
            image_filter,
            mkt,
            license,
            ddg_safe_search,
            ddg_region,
            adult_filter_off,
            cancel,
            min_dimension,
        )

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

        # All per-run mutable state (result lists, counters) and the
        # engine hook wiring live in a _SearchSession so this method
        # stays an orchestration outline: setup -> run -> finish.
        _fire_hook(self.on_engine_start, engine, query)
        session = _SearchSession(self, engine_obj, engine, query, limit, manifest_ctx)
        session.install()

        try:
            engine_obj.run()
        finally:
            # Detach the session and close the manifest writer, even on
            # exception. Both are idempotent.
            session.uninstall()
            if manifest_writer is not None:
                manifest_writer.close()

        return session.build_result(image_dir, manifest_abs_path, cancel)

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
        min_dimension: int | None = None,
        license: str = "any",
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
            min_dimension=min_dimension,
            license=license,
        )


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
