from array import array
from typing import BinaryIO, Sequence

PAGE_SIZES = {"a4": (595.276, 841.89), "letter": (612.0, 792.0)}  # points

_MARGIN = 56.693  # 2 cm
_CHAR_WIDTH = 0.6  # Courier: every glyph is 600/1000 em wide
_LINE_SPACING = 1.2
_HEADER = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"

# Fixed object numbers; page objects follow in pairs (page, content stream).
_CATALOG, _PAGES, _FONT, _FIRST_PAGE = 1, 2, 3, 4
_XREF_CHUNK = 1000


class TextPdfWriter:
    """Writes monospaced text to a PDF, one page at a time.

    Uses the built-in Courier font with WinAnsi encoding, so lines must be
    bytes encoded as cp1252. No metadata (dates, author, producer) is written,
    and the output is deterministic. Call ``close()`` to finish the file.
    """

    def __init__(self, out: BinaryIO, page_size: str = "a4", font_size: int = 10) -> None:
        self._out = out
        self._pos = 0
        self._offsets = array("Q")  # byte position of each object, indexed by object number
        self._page_count = 0
        self._width, self._height = PAGE_SIZES[page_size]
        self._font_size = font_size
        self._leading = font_size * _LINE_SPACING
        self.columns = int((self._width - 2 * _MARGIN) // (font_size * _CHAR_WIDTH))
        self.lines_per_page = int((self._height - 2 * _MARGIN) // self._leading)
        self._write(_HEADER)
        self._write_object(
            _FONT,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        )

    def add_page(self, lines: Sequence[bytes]) -> None:
        if len(lines) > self.lines_per_page:
            raise ValueError("Too many lines for one page.")
        number = _FIRST_PAGE + 2 * self._page_count
        top = self._height - _MARGIN - self._font_size
        head = (
            f"BT\n/F1 {self._font_size} Tf\n{self._leading:g} TL\n"
            f"{_MARGIN:.3f} {top:.3f} Td\n"
        ).encode()
        rows = (b"(" + _escape(line) + b") Tj T*\n" for line in lines)
        stream = b"".join((head, *rows, b"ET"))
        self._write_object(
            number, f"<< /Type /Page /Parent {_PAGES} 0 R /Contents {number + 1} 0 R >>".encode()
        )
        self._write_object(
            number + 1, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
        self._page_count += 1

    def close(self) -> None:
        if not self._page_count:
            self.add_page([])
        kids = " ".join(
            f"{number} 0 R" for number in range(_FIRST_PAGE, _FIRST_PAGE + 2 * self._page_count, 2)
        )
        self._write_object(
            _PAGES,
            (
                f"<< /Type /Pages /Kids [{kids}] /Count {self._page_count} "
                f"/MediaBox [0 0 {self._width:g} {self._height:g}] "
                f"/Resources << /Font << /F1 {_FONT} 0 R >> >> >>"
            ).encode(),
        )
        self._write_object(_CATALOG, f"<< /Type /Catalog /Pages {_PAGES} 0 R >>".encode())

        xref_position = self._pos
        size = len(self._offsets)
        self._write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
        for first in range(1, size, _XREF_CHUNK):
            chunk = range(first, min(first + _XREF_CHUNK, size))
            self._write("".join(f"{self._offsets[n]:010d} 00000 n \n" for n in chunk).encode())
        self._write(
            (
                f"trailer\n<< /Size {size} /Root {_CATALOG} 0 R >>\n"
                f"startxref\n{xref_position}\n%%EOF\n"
            ).encode()
        )

    def _write(self, data: bytes) -> None:
        self._out.write(data)
        self._pos += len(data)

    def _write_object(self, number: int, body: bytes) -> None:
        self._offsets.extend([0] * (number + 1 - len(self._offsets)))
        self._offsets[number] = self._pos
        self._write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")


def _escape(line: bytes) -> bytes:
    return line.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
