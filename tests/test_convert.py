import os
import sys

import pytest

from lfconv import (
    ConversionError,
    ConverterError,
    InvalidFileError,
    InvalidOptionError,
    OutputError,
    UnsupportedFormatError,
    convert,
)

pytestmark = pytest.mark.usefixtures("upper_converter")

posix_non_root = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission tests need a POSIX non-root user",
)


def leftovers(folder):
    return sorted(p.name for p in folder.iterdir())


# --- happy paths ---------------------------------------------------------

def test_converts_and_returns_output_path(src, tmp_path):
    out = tmp_path / "out.up"
    assert convert(src, out) == out
    assert out.read_text(encoding="utf-8") == "HELLO"


def test_accepts_string_paths(src, tmp_path):
    convert(str(src), str(tmp_path / "out.up"))
    assert (tmp_path / "out.up").exists()


def test_explicit_formats_override_extensions(tmp_path):
    odd = tmp_path / "data.bin"
    odd.write_text("abc", encoding="utf-8")
    convert(odd, tmp_path / "result.out", "txt", "up")
    assert (tmp_path / "result.out").read_text(encoding="utf-8") == "ABC"


def test_options_reach_the_converter(src, tmp_path):
    convert(src, tmp_path / "out.up", options={"repeat": 2})
    assert (tmp_path / "out.up").read_text(encoding="utf-8") == "HELLOHELLO"


def test_output_folder_is_created(src, tmp_path):
    out = tmp_path / "a" / "b" / "out.up"
    convert(src, out)
    assert out.exists()


def test_converter_sees_a_temp_file_with_the_target_extension(src, tmp_path, fresh_registry):
    seen = {}

    def spy(source, destination, options):
        seen["dst"] = destination
        destination.write_text("x", encoding="utf-8")

    fresh_registry.register("txt", "spy", spy)
    out = tmp_path / "result.spy"
    convert(src, out)
    assert seen["dst"].suffix == ".spy"
    assert seen["dst"] != out
    assert leftovers(tmp_path) == ["in.txt", "result.spy"]


# --- unsupported / undetectable formats ------------------------------------

def test_unsupported_target(src, tmp_path):
    with pytest.raises(UnsupportedFormatError):
        convert(src, tmp_path / "out.zzz")


def test_unsupported_source(tmp_path):
    f = tmp_path / "file.zzz"
    f.write_text("abc", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        convert(f, tmp_path / "out.up")


def test_undetectable_source_format(tmp_path):
    f = tmp_path / "noext"
    f.write_text("abc", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="input format"):
        convert(f, tmp_path / "out.up")


def test_undetectable_target_format(src, tmp_path):
    with pytest.raises(UnsupportedFormatError, match="output format"):
        convert(src, tmp_path / "noext")


# --- bad input ---------------------------------------------------------------

def test_missing_input(tmp_path):
    with pytest.raises(InvalidFileError, match="not found"):
        convert(tmp_path / "missing.txt", tmp_path / "out.up")


def test_directory_as_input(tmp_path):
    folder = tmp_path / "folder.txt"
    folder.mkdir()
    with pytest.raises(InvalidFileError, match="not a file"):
        convert(folder, tmp_path / "out.up")


def test_empty_input(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(InvalidFileError, match="empty"):
        convert(empty, tmp_path / "out.up")
    assert leftovers(tmp_path) == ["empty.txt"]


def test_invalid_option_fails_before_writing(src, tmp_path):
    with pytest.raises(InvalidOptionError):
        convert(src, tmp_path / "out.up", options={"repeat": 99})
    assert leftovers(tmp_path) == ["in.txt"]


def test_error_messages_do_not_leak_full_paths(tmp_path):
    deep = tmp_path / "private" / "folder"
    with pytest.raises(InvalidFileError) as info:
        convert(deep / "secret.txt", tmp_path / "out.up")
    assert str(tmp_path) not in str(info.value)
    assert "secret.txt" in str(info.value)


# --- output handling -----------------------------------------------------------

def test_existing_output_is_not_overwritten_by_default(src, tmp_path):
    out = tmp_path / "out.up"
    out.write_text("original", encoding="utf-8")
    with pytest.raises(OutputError, match="already exists"):
        convert(src, out)
    assert out.read_text(encoding="utf-8") == "original"


def test_overwrite_replaces_existing_output(src, tmp_path):
    out = tmp_path / "out.up"
    out.write_text("original", encoding="utf-8")
    convert(src, out, overwrite=True)
    assert out.read_text(encoding="utf-8") == "HELLO"


def test_output_cannot_be_the_input(src):
    with pytest.raises(OutputError, match="overwrite the input"):
        convert(src, src, "txt", "up", overwrite=True)
    assert src.read_text(encoding="utf-8") == "hello"


def test_output_cannot_be_a_folder(src, tmp_path):
    folder = tmp_path / "out.up"
    folder.mkdir()
    with pytest.raises(OutputError, match="folder"):
        convert(src, folder, overwrite=True)


def test_output_folder_path_blocked_by_a_file(src, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(OutputError):
        convert(src, blocker / "out.up")


@posix_non_root
def test_read_only_output_folder(src, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(OutputError, match="not writable"):
            convert(src, locked / "out.up")
    finally:
        locked.chmod(0o700)


@posix_non_root
def test_unreadable_input(src, tmp_path):
    src.chmod(0o000)
    try:
        with pytest.raises(InvalidFileError, match="cannot be read"):
            convert(src, tmp_path / "out.up")
    finally:
        src.chmod(0o600)


# --- failures inside converters --------------------------------------------------

def test_unexpected_exception_becomes_conversion_error(src, tmp_path, fresh_registry):
    def boom(source, destination, options):
        destination.write_bytes(b"partial")
        raise RuntimeError("internal detail")

    fresh_registry.register("txt", "bad", boom)
    with pytest.raises(ConversionError) as info:
        convert(src, tmp_path / "out.bad")
    assert "internal detail" not in str(info.value)
    assert isinstance(info.value.__cause__, RuntimeError)
    assert leftovers(tmp_path) == ["in.txt"]


def test_failure_keeps_existing_output_intact(src, tmp_path, fresh_registry):
    def boom(source, destination, options):
        destination.write_bytes(b"partial")
        raise RuntimeError

    fresh_registry.register("txt", "bad", boom)
    out = tmp_path / "out.bad"
    out.write_text("original", encoding="utf-8")
    with pytest.raises(ConversionError):
        convert(src, out, overwrite=True)
    assert out.read_text(encoding="utf-8") == "original"
    assert leftovers(tmp_path) == ["in.txt", "out.bad"]


def test_converter_errors_propagate_unchanged(src, tmp_path, fresh_registry):
    def reject(source, destination, options):
        raise InvalidFileError("Not a valid file.")

    fresh_registry.register("txt", "bad", reject)
    with pytest.raises(InvalidFileError, match="Not a valid file") as info:
        convert(src, tmp_path / "out.bad")
    assert isinstance(info.value, ConverterError)
    assert leftovers(tmp_path) == ["in.txt"]


def test_os_error_in_converter_becomes_output_error(src, tmp_path, fresh_registry):
    def disk_full(source, destination, options):
        raise OSError(28, "No space left on device")

    fresh_registry.register("txt", "bad", disk_full)
    with pytest.raises(OutputError) as info:
        convert(src, tmp_path / "out.bad")
    assert isinstance(info.value.__cause__, OSError)


def test_converter_that_writes_nothing_is_an_error(src, tmp_path, fresh_registry):
    fresh_registry.register("txt", "none", lambda s, d, o: None)
    with pytest.raises(ConversionError):
        convert(src, tmp_path / "out.none")
