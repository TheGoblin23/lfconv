import os

from .errors import UnsupportedFormatError

_ALIASES = {"jpeg": "jpg", "tif": "tiff"}


def normalize_format(name: str) -> str:
    """Return the canonical form of a format name: ``".JPEG"`` -> ``"jpg"``."""
    fmt = name.strip().lstrip(".").lower()
    if not fmt:
        raise UnsupportedFormatError("The format name is empty.")
    return _ALIASES.get(fmt, fmt)


def format_from_path(path: str | os.PathLike[str]) -> str | None:
    """Guess the format from the file extension, or None if there is none."""
    suffix = os.path.splitext(os.fspath(path))[1].lstrip(".")
    return normalize_format(suffix) if suffix else None
