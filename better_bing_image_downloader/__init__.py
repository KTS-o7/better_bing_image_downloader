import logging
from .bing import Bing
from .download import downloader

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["Bing", "downloader"]

# ``DuckDuckGo`` is exposed lazily because importing it requires the
# optional ``brotli`` package.  This lets users of the Bing-only path
# install without brotli.
try:
    from .duckduckgo import DuckDuckGo  # noqa: F401
    __all__.append("DuckDuckGo")
except ImportError:  # pragma: no cover
    pass
