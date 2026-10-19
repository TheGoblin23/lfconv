"""Every user-facing string of the GUI, in one place so it can be translated."""

from ..core.errors import ConverterError

TITLE = "Local File Converter"

ADD_FILES = "Add files…"
ADD_FOLDER = "Add folder…"
REMOVE = "Remove"
CLEAR = "Clear"
CONVERT_TO = "Convert to:"
SAVE_IN = "Save in:"
SAME_FOLDER = "Same folder as the original"
CHOOSE = "Choose…"
RESET = "Reset"
OVERWRITE = "Replace existing files"
CONVERT = "Convert"

COLUMN_FILE = "File"
COLUMN_TYPE = "Type"
COLUMN_STATUS = "Status"

SUPPORTED_FILES = "Supported files"
ALL_FILES = "All files"
PICK_FILES = "Choose files to convert"
PICK_FOLDER = "Choose a folder to convert"
PICK_OUTPUT = "Choose where to save the results"

HINT_EMPTY = "Add files or a folder to begin."
STATUS_CONVERTING = "Converting…"
STATUS_DONE = "Done: {name}"
STATUS_UNAVAILABLE = "Cannot convert to {target}"
STOPPING = "Stopping after the current file…"

ERROR_TITLE = "Cannot convert"
NOTHING_TO_CONVERT = "None of the files in the list can be converted to {target}."
FAILED_TITLE = "Could not convert the file."
INTERNAL_ERROR = "Something went wrong while converting this file."
SOME_FAILED_TITLE = "Some files were not converted"
SOME_FAILED_HINT = "Select a file in the list to see the details."

CLOSE_BUSY_TITLE = "Conversion in progress"
CLOSE_BUSY = "Stop converting and quit?\n\nThe file being converted will be finished first."

_FORMAT_NAMES = {"webp": "WebP", "jpg": "JPG", "png": "PNG", "pdf": "PDF",
                 "csv": "CSV", "json": "JSON", "txt": "TXT"}
_OPTION_NAMES = {"page_size": "Page size", "font_size": "Font size"}


def format_name(fmt: str) -> str:
    return _FORMAT_NAMES.get(fmt, fmt.upper())


def option_name(name: str) -> str:
    return _OPTION_NAMES.get(name, name.replace("_", " ").capitalize())


def files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def ready(count: int) -> str:
    return f"{files(count)} ready to convert."


def added(added: int, unsupported: int, duplicates: int) -> str:
    parts = [f"{files(added)} added"]
    if unsupported:
        parts.append(f"{unsupported} not supported")
    if duplicates:
        parts.append(f"{duplicates} already in the list")
    return ", ".join(parts) + "."


def progress(done: int, total: int) -> str:
    return f"Converting… {done} of {total}"


def finished(converted: int, failed: int, stopped: bool, total: int) -> str:
    if stopped:
        return f"Stopped: {converted} of {total} converted" + (f", {failed} failed." if failed else ".")
    if failed:
        return f"{converted} converted, {failed} failed."
    return f"All {files(converted)} converted." if converted > 1 else "File converted."


def failure_reason(error: Exception) -> str:
    """The reason shown to people; internal details never reach the window."""
    return str(error) if isinstance(error, ConverterError) else INTERNAL_ERROR
