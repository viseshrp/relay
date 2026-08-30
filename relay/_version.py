"The version module for the relay package."

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("relay-ai")
except PackageNotFoundError:  # pragma: no cover
    try:
        __version__ = version("relay")
    except PackageNotFoundError:
        # Fallback for local dev or editable installs
        __version__ = "0.0.0"
