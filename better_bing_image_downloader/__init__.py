import logging

from .base import ImageEngine
from .bing import Bing
from .download import downloader
from .downloader import CancelToken, Downloader
from .results import ImageResult, Result

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "Bing",
    "CancelToken",
    "Downloader",
    "ImageEngine",
    "ImageResult",
    "Result",
    "downloader",
]

# ``DuckDuckGo`` is exposed eagerly as of v3.1.1: ``brotli`` is a hard
# dependency, so the import always succeeds. The try/except is kept
# for compatibility with users on older Python builds where the
# conditional import might still apply.
try:
    from .duckduckgo import DuckDuckGo  # noqa: F401

    __all__.append("DuckDuckGo")
except ImportError:  # pragma: no cover
    pass
