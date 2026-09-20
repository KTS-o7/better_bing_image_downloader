"""Thread-safe one-shot cancellation flag (split out of ``downloader.py``).

Moved here in the downloader.py split (#83) with zero behaviour change.
Import from :mod:`better_bing_image_downloader.downloader` as before —
it re-exports :class:`CancelToken`.
"""

from __future__ import annotations

import threading

__all__ = ["CancelToken"]


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
