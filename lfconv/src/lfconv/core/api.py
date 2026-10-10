import contextlib
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping

from . import registry
from .errors import (
    ConversionError,
    ConverterError,
    InvalidFileError,
    OutputError,
    UnsupportedFormatError,
)
from .formats import format_from_path, normalize_format
from .options import validate_options
from .registry import ConvertFunc

PathLike = str | os.PathLike[str]


def can_convert(source_format: str, target_format: str) -> bool:
    return registry.get_registry().can_convert(source_format, target_format)


def get_available_conversions(source_format: str) -> list[str]:
    """Target formats reachable from ``source_format``, sorted."""
    return registry.get_registry().targets(source_format)


def describe_converters() -> list[dict[str, Any]]:
    """Every registered conversion and its options, as plain data."""
    return registry.get_registry().describe()


def convert(
    input_path: PathLike,
    output_path: PathLike,
    source_format: str | None = None,
    target_format: str | None = None,
    options: Mapping[str, Any] | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Convert one file and return the output path.

    Formats default to the file extensions. The output is written to a
    temporary file and renamed on success, so a failure never leaves a
    partial file behind. Missing output folders are created.

    Raises a subclass of ``ConverterError`` on any failure.
    """
    src, dst = Path(input_path), Path(output_path)
    _check_input(src)
    source = _resolve_format(source_format, src, "input")
    target = _resolve_format(target_format, dst, "output")
    info = registry.get_registry().get(source, target)
    resolved = validate_options(info.options, options)
    _prepare_output(src, dst, overwrite)
    _run_atomically(info.func, src, dst, resolved)
    return dst


def _resolve_format(explicit: str | None, path: Path, role: str) -> str:
    fmt = normalize_format(explicit) if explicit else format_from_path(path)
    if fmt is None:
        raise UnsupportedFormatError(f"Could not determine the {role} format of '{path.name}'.")
    return fmt


def _check_input(src: Path) -> None:
    try:
        mode = src.stat().st_mode
    except FileNotFoundError as exc:
        raise InvalidFileError(f"File not found: '{src.name}'.") from exc
    except OSError as exc:
        raise InvalidFileError(f"'{src.name}' cannot be read.") from exc
    if not stat.S_ISREG(mode):
        raise InvalidFileError(f"'{src.name}' is not a file.")
    try:
        with src.open("rb") as handle:
            empty = not handle.read(1)
    except OSError as exc:
        raise InvalidFileError(f"'{src.name}' cannot be read.") from exc
    if empty:
        raise InvalidFileError(f"'{src.name}' is empty.")


def _prepare_output(src: Path, dst: Path, overwrite: bool) -> None:
    if dst.exists() and os.path.samefile(src, dst):
        raise OutputError("The output would overwrite the input file.")
    if dst.is_dir():
        raise OutputError(f"'{dst.name}' is a folder.")
    if dst.exists() and not overwrite:
        raise OutputError(f"'{dst.name}' already exists.")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError("Could not create the output folder.") from exc
    if not os.access(dst.parent, os.W_OK):
        raise OutputError("The output folder is not writable.")


def _run_atomically(func: ConvertFunc, src: Path, dst: Path, options: dict[str, Any]) -> None:
    # Same folder as the destination so the final rename is atomic; same
    # file name at the end so the temporary file keeps the right extension.
    tmp = dst.with_name(f".{uuid.uuid4().hex[:8]}-{dst.name}")
    try:
        try:
            func(src, tmp, options)
        except ConverterError:
            raise
        except OSError as exc:
            raise OutputError("Could not write the output file.") from exc
        except Exception as exc:
            raise ConversionError(f"Could not convert '{src.name}'.") from exc
        if not tmp.exists():
            raise ConversionError(f"Could not convert '{src.name}'.")
        try:
            os.replace(tmp, dst)
        except OSError as exc:
            raise OutputError(f"Could not save '{dst.name}'.") from exc
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
