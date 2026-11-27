"""Backend compatibility package for ProxyHunter v3.0.

The proven v2.0 engine remains in ``proxyhunter``. This package exposes a
UI-agnostic controller used by both frontends.
"""

from proxyhunter import __version__

from .controller import BackendController, BackendWorker

__all__ = ["BackendController", "BackendWorker", "__version__"]
