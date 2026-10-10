import io
import re
import tracemalloc

import pytest

from lfconv import InvalidFileError, InvalidOptionError, can_convert, convert
from lfconv.converters import text as text_converters
from lfconv.converters.pdf_writer import TextPdfWriter


@pytest.fixture(autouse=True)
def builtin():
    text_converters.register()


def make_pdf(tmp_path, content, **options):
    src = tmp_path / "in.txt"
    src.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    out = tmp_path / "out.pdf"
    convert(src, out, options=options, overwrite=True)
    return out.read_bytes()


def check_structure(data):
    """Independent check of header, xref offsets, trailer and page count."""
    assert data.startswith(b"%PDF-1.4\n")
    tail = re.search(rb"startxref\n(\d+)\n%%EOF\n\Z", data)
    assert tail, "missing startxref/EOF"
    xref = int(tail.group(1))
    header = re.match(rb"xref\n0 (\d+)\n", data[xref:xref + 40])
    size = int(header.group(1))
    start = xref + header.end()
    assert data[start:start + 20] == b"0000000000 65535 f \n"
    for number in range(1, size):
        entry = data[start + 20 * number: start + 20 * (number + 1)]
        assert re.fullmatch(rb"\d{10} 00000 n \n", entry)
        assert data.startswith(f"{number} 0 obj\n".encode(), int(entry[:10]))
    assert f"/Size {size} /Root 1 0 R".encode() in data
    count = int(re.search(rb"/Count (\d+)", data).group(1))
    assert len(re.findall(rb"/Type /Page(?!s)", data)) == count
    return count


def pages_of(data):
    """Rows of text drawn on each page, read back from the content streams."""
    pages = []
    for stream in re.finditer(rb"(?<!end)stream\n(.*?)\nendstream", data, re.S):
        rows = re.findall(rb"^\((.*)\) Tj T\*$", stream.group(1), re.M)
        pages.append([re.sub(rb"\\(.)", rb"\1", row, flags=re.S).decode("cp1252") for row in rows])
    return pages


def all_rows(data):
    return [row for page in pages_of(data) for row in page]


# --- registration -------------------------------------------------------------

def test_txt_to_pdf_is_registered():
    assert can_convert("txt", "pdf")
    assert not can_convert("pdf", "txt")


# --- the PDF writer ------------------------------------------------------------

def test_page_geometry():
    a4 = TextPdfWriter(io.BytesIO())
    assert (a4.columns, a4.lines_per_page) == (80, 60)
    letter = TextPdfWriter(io.BytesIO(), "letter")
    assert (letter.columns, letter.lines_per_page) == (83, 56)
    big = TextPdfWriter(io.BytesIO(), "a4", 20)
    assert big.columns == 40


def test_writer_rejects_overfull_page():
    writer = TextPdfWriter(io.BytesIO())
    with pytest.raises(ValueError):
        writer.add_page([b"x"] * (writer.lines_per_page + 1))


def test_writer_without_pages_still_makes_a_valid_document():
    buffer = io.BytesIO()
    TextPdfWriter(buffer).close()
    assert check_structure(buffer.getvalue()) == 1


# --- conversion ----------------------------------------------------------------

def test_basic_text(tmp_path):
    data = make_pdf(tmp_path, "hello\nworld\n")
    assert check_structure(data) == 1
    assert all_rows(data) == ["hello", "world"]


def test_accents_symbols_and_special_characters_round_trip(tmp_path):
    line = "Ñandú: áéíóú ü € “comillas” — (paréntesis) \\ barra"
    assert all_rows(make_pdf(tmp_path, line)) == [line]


def test_characters_outside_cp1252_become_question_marks(tmp_path):
    assert all_rows(make_pdf(tmp_path, "a 😀 中 b")) == ["a ? ? b"]


def test_decomposed_accents_are_normalized(tmp_path):
    assert all_rows(make_pdf(tmp_path, "n\u0303")) == ["ñ"]


def test_tabs_are_expanded_and_control_characters_dropped(tmp_path):
    assert all_rows(make_pdf(tmp_path, "a\tb\n\x00\x0cc\x7f")) == ["a   b", "c"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_all_newline_styles_and_blank_lines(tmp_path, newline):
    content = newline.join(["a", "", "", "b"])
    assert all_rows(make_pdf(tmp_path, content)) == ["a", "", "", "b"]


def test_bom_is_ignored(tmp_path):
    assert all_rows(make_pdf(tmp_path, b"\xef\xbb\xbfhola")) == ["hola"]


def test_long_lines_wrap_at_the_page_width(tmp_path):
    rows = all_rows(make_pdf(tmp_path, "x" * 200))
    assert [len(r) for r in rows] == [80, 80, 40]


def test_pages_fill_up_then_continue(tmp_path):
    data = make_pdf(tmp_path, "\n".join(f"line {i}" for i in range(130)))
    assert check_structure(data) == 3
    assert [len(p) for p in pages_of(data)] == [60, 60, 10]


def test_whitespace_only_file_gives_one_blank_page(tmp_path):
    data = make_pdf(tmp_path, "\n\n")
    assert check_structure(data) == 1


def test_options_change_layout(tmp_path):
    data = make_pdf(tmp_path, "x" * 100, font_size=20)
    assert [len(r) for r in all_rows(data)] == [40, 40, 20]
    assert b"[0 0 612 792]" in make_pdf(tmp_path, "hi", page_size="letter")
    assert b"[0 0 595.276 841.89]" in make_pdf(tmp_path, "hi")


@pytest.mark.parametrize("options", [{"font_size": 5}, {"font_size": 25}, {"page_size": "a0"}])
def test_invalid_options_are_rejected(tmp_path, options):
    src = tmp_path / "in.txt"
    src.write_text("hi", encoding="utf-8")
    with pytest.raises(InvalidOptionError):
        convert(src, tmp_path / "out.pdf", options=options)


def test_output_is_deterministic_and_carries_no_metadata(tmp_path):
    first = make_pdf(tmp_path, "secret text")
    second = make_pdf(tmp_path, "secret text", page_size="a4")
    assert first == second
    for marker in (b"/Info", b"/Producer", b"/CreationDate", b"/Author", b"in.txt"):
        assert marker not in first


# --- invalid input ---------------------------------------------------------------

@pytest.mark.parametrize("content", [b"caf\xe9\n", b"\x89PNG\r\n\x1a\n\x00\x00", b"\xff\xfeh\x00i\x00"])
def test_non_utf8_input_is_rejected(tmp_path, content):
    src = tmp_path / "in.txt"
    src.write_bytes(content)
    with pytest.raises(InvalidFileError, match="not valid UTF-8"):
        convert(src, tmp_path / "out.pdf")
    assert [p.name for p in tmp_path.iterdir()] == ["in.txt"]


def test_invalid_bytes_late_in_the_file_leave_no_partial_output(tmp_path):
    src = tmp_path / "in.txt"
    src.write_bytes(b"ok line\n" * 5000 + b"bad \xe9 byte\n")
    with pytest.raises(InvalidFileError):
        convert(src, tmp_path / "out.pdf")
    assert [p.name for p in tmp_path.iterdir()] == ["in.txt"]


# --- independent readers ----------------------------------------------------------

def test_pypdf_reads_the_output(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    data = make_pdf(tmp_path, "Ñandú (1) \\ €\n" + "\n".join(f"n{i}" for i in range(70)))
    reader = pypdf.PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 2
    first = reader.pages[0].extract_text()
    assert "Ñandú (1) \\ €" in first
    assert "n58" in first and "n59" not in first
    assert "n59" in reader.pages[1].extract_text()
    assert [float(v) for v in reader.pages[0].mediabox] == [0, 0, 595.276, 841.89]


@pytest.mark.slow
def test_large_file_streams_with_low_memory(tmp_path):
    src = tmp_path / "big.txt"
    with src.open("w", encoding="utf-8") as f:
        for i in range(200_000):
            f.write(f"line {i} " + "x" * 40 + "\n")
    size = src.stat().st_size

    tracemalloc.start()
    convert(src, tmp_path / "big.pdf")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < size / 8
    data = (tmp_path / "big.pdf").read_bytes()
    assert check_structure(data) == -(-200_000 // 60)
