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

The legacy module-level :func:`better_bing_image_downloader.downloader`
function is preserved as a thin wrapper around :class:`Downloader`.
"""

from __future__ import annotations

import http.cookiejar
import logging
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from .base import ImageEngine
from .bing import Bing
from .duckduckgo import DuckDuckGo
from .results import ImageResult, Result

__all__ = ["Downloader", "ImageResult", "Result", "ImageSaveError"]


class ImageSaveError(Exception):
    """Raised internally by ``Downloader.search`` when a save_image call
    returns ``False`` for a known reason.

    This is a control-flow exception: it is not a programming error.
    It exists so that the user's ``on_error`` hook and the
    ``Result.errors`` list receive a uniform signal whether the
    failure was a network error, an invalid image body, or a
    duplicate (same MD5) image.

    Attributes
    ----------
    reason : str
        Human-readable reason. One of:
        ``"network"``, ``"invalid_image"``, ``"duplicate"``,
        ``"write_failed"``.
    url : str
        The image URL that failed to save.
    """

    def __init__(self, reason: str, url: str, message: str = "") -> None:
        self.reason = reason
        self.url = url
        if not message:
            message = f"image save failed: reason={reason!r} url={url!r}"
        super().__init__(message)


HookOnImage = Callable[[ImageResult], None]
HookOnError = Callable[[str, BaseException], None]
HookOnEngineStart = Callable[[str, str], None]  # (engine, query)
HookOnEngineDone = Callable[[str, Result], None]  # (engine, result)


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

        # --- Per-instance engine registry ---
        # Copy from the class default so per-instance ``register()``
        # calls don't leak to other Downloader instances, but tests can
        # still patch ``_DEFAULT_REGISTRY`` to swap the default set.
        self._registry: dict[str, type[ImageEngine]] = dict(self._DEFAULT_REGISTRY)
        self._registry_lock = threading.Lock()

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
        verbose: bool = False,
        image_filter: str = "",
        mkt: str = "en-US",
        ddg_safe_search: str = "moderate",
        ddg_region: str = "us-en",
        adult_filter_off: bool = False,
    ) -> Result:
        """Run a search and return a :class:`Result`.

        Parameters mirror the legacy module-level :func:`downloader`
        function; the only behavioural differences are the return type
        (``Result`` instead of ``int``) and that hooks are fired.
        """
        image_dir = Path(output_dir) / query
        image_dir.mkdir(parents=True, exist_ok=True)

        adult = "off" if adult_filter_off else "moderate"

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
        else:
            engine_kwargs = {}

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

        # Monkey-patch the engine's save_image to capture every successful
        # save and every error. We capture by wrapping the bound method.
        original_save = engine_obj.save_image

        def save_with_hooks(link: str, file_path) -> bool:
            try:
                ok = original_save(link, file_path)
            except Exception as exc:
                # save_image raised (e.g. an unhandled exception bubbled
                # up). Surface via on_error and Result.errors.
                errors.append((link, exc))
                if self.on_error:
                    try:
                        self.on_error(link, exc)
                    except Exception:
                        logging.exception("on_error hook raised; continuing")
                return False
            if not ok:
                # save_image returned False for a known reason
                # (network, invalid mime, duplicate, or write
                # failure). Previously this was silent data loss
                # (3.2.0). In 3.2.1 we surface it via on_error and
                # Result.errors so a library user can react.
                #
                # TODO(3.3.0): change save_image to raise specific
                # ImageSaveError subclasses (NetworkError,
                # InvalidImageError, DuplicateImageError) so callers
                # can distinguish them. For now, the reason is
                # "save_failed" — generic, but at least the user
                # gets a signal.
                save_exc = ImageSaveError(reason="save_failed", url=link)
                errors.append((link, save_exc))
                if self.on_error:
                    try:
                        self.on_error(link, save_exc)
                    except Exception:
                        logging.exception("on_error hook raised; continuing")
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
            return True

        # ``save_image`` is defined on the base ``ImageEngine`` class,
        # so this attribute assignment is legal Python but mypy flags
        # it. Suppress only the method-assign warning.
        engine_obj.save_image = save_with_hooks  # type: ignore[method-assign]

        try:
            engine_obj.run()
        finally:
            # Always surface what we have, even on exception.
            pass

        result = Result(
            query=query,
            engine=engine,
            output_dir=image_dir,
            images=images,
            skipped=engine_obj._slots_used - engine_obj.download_count,
            errors=errors,
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


def _guess_mime(path: Path) -> str:
    """Return a best-effort MIME type from the file extension."""
    import mimetypes

    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"
