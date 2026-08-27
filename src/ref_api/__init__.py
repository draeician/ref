"""HTTP API for recording URL references (same archive as ref CLI)."""

__all__ = ["__version__"]

try:
    from ref_cli import __version__
except ImportError:
    __version__ = "unknown"
