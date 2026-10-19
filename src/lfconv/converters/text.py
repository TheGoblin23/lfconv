import unicodedata
from pathlib import Path
from typing import Any, Iterator

from ..core.errors import InvalidFileError
from ..core.options import Option
from ..core.registry import register_converter
from .pdf_writer import TextPdfWriter

_TAB_SIZE = 4
_CONTROL_CHARS = {code: None for code in (*range(32), 127)}

_PDF_OPTIONS = (
    Option("page_size", "str", "a4", "Page size.", choices=("a4", "letter")),
    Option("font_size", "int", 10, "Font size in points.", min=6, max=24),
)


def register() -> None:
    register_converter("txt", "pdf", txt_to_pdf, _PDF_OPTIONS, replace=True)


def txt_to_pdf(src: Path, dst: Path, options: dict[str, Any]) -> None:
    """Write a UTF-8 text file as a monospaced PDF, streaming page by page.

    Characters outside Windows-1252 (emoji, CJK, ...) become "?".
    """
    try:
        with src.open(encoding="utf-8-sig") as fin, dst.open("wb") as fout:
            writer = TextPdfWriter(fout, options["page_size"], options["font_size"])
            page: list[bytes] = []
            for line in fin:
                for row in _wrap(_clean(line), writer.columns):
                    page.append(row.encode("cp1252", errors="replace"))
                    if len(page) == writer.lines_per_page:
                        writer.add_page(page)
                        page = []
            if page:
                writer.add_page(page)
            writer.close()
    except UnicodeDecodeError as exc:
        raise InvalidFileError("The file is not valid UTF-8 text.") from exc


def _clean(line: str) -> str:
    text = unicodedata.normalize("NFC", line.rstrip("\n"))
    return text.expandtabs(_TAB_SIZE).translate(_CONTROL_CHARS)


def _wrap(text: str, width: int) -> Iterator[str]:
    if not text:
        yield ""
    for start in range(0, len(text), width):
        yield text[start:start + width]
