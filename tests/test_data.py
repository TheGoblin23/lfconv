import json
import tracemalloc

import pytest

from lfconv import InvalidFileError, can_convert, convert, describe_converters
from lfconv.converters import data as data_converters


@pytest.fixture(autouse=True)
def builtin():
    data_converters.register()


def make(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def leftovers(folder):
    return sorted(p.name for p in folder.iterdir())


def to_json(tmp_path, content, **options):
    src = make(tmp_path, "in.csv", content)
    out = tmp_path / "out.json"
    convert(src, out, options=options)
    return out.read_text(encoding="utf-8")


def to_csv(tmp_path, content, **options):
    src = make(tmp_path, "in.json", content)
    out = tmp_path / "out.csv"
    convert(src, out, options=options)
    return out.read_bytes().decode("utf-8")


# --- loading ---------------------------------------------------------------

def test_builtin_conversions_are_registered():
    assert can_convert("csv", "json")
    assert can_convert("json", "csv")
    assert can_convert("json", "txt")
    assert not can_convert("txt", "json")


def test_registering_twice_is_harmless():
    data_converters.register()
    assert len(describe_converters()) == 3


# --- csv -> json -----------------------------------------------------------

def test_csv_to_json_basic_values_stay_strings(tmp_path):
    text = to_json(tmp_path, "name,age\nAna,30\nLuis,25\n")
    assert json.loads(text) == [{"name": "Ana", "age": "30"}, {"name": "Luis", "age": "25"}]


def test_csv_to_json_keeps_unicode_readable(tmp_path):
    text = to_json(tmp_path, "nombre\nNiño\n")
    assert "Niño" in text


def test_csv_to_json_auto_detects_semicolon(tmp_path):
    assert json.loads(to_json(tmp_path, "a;b\n1;2\n")) == [{"a": "1", "b": "2"}]


def test_csv_to_json_explicit_delimiter(tmp_path):
    assert json.loads(to_json(tmp_path, "a|b\n1|2\n", delimiter="|")) == [{"a": "1", "b": "2"}]


def test_csv_to_json_ignores_bom(tmp_path):
    text = to_json(tmp_path, b"\xef\xbb\xbfname\nAna\n")
    assert json.loads(text) == [{"name": "Ana"}]


def test_csv_to_json_quoted_fields_and_crlf(tmp_path):
    text = to_json(tmp_path, 'a,b\r\n"x, y","line1\nline2"\r\n')
    assert json.loads(text) == [{"a": "x, y", "b": "line1\nline2"}]


def test_csv_to_json_skips_blank_lines(tmp_path):
    assert json.loads(to_json(tmp_path, "a\n\n1\n\n2\n")) == [{"a": "1"}, {"a": "2"}]


def test_csv_to_json_header_only_gives_empty_list(tmp_path):
    assert json.loads(to_json(tmp_path, "a,b\n")) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("a,b\n1,2\n3\n", "Line 3 has 1 columns"),
        ("a,a\n1,2\n", "duplicate"),
        ("\n\n", "no header"),
        (b"a,b\n\xe9,1\n", "not a valid CSV"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "not a valid CSV"),
    ],
)
def test_csv_to_json_invalid_files(tmp_path, content, message):
    src = make(tmp_path, "in.csv", content)
    with pytest.raises(InvalidFileError, match=message):
        convert(src, tmp_path / "out.json")
    assert leftovers(tmp_path) == ["in.csv"]


@pytest.mark.slow
def test_csv_to_json_streams_large_files(tmp_path):
    rows = 150_000
    src = tmp_path / "big.csv"
    with src.open("w", encoding="utf-8") as f:
        f.write("id,name,email,city\n")
        for i in range(rows):
            f.write(f"{i},user{i},user{i}@example.com,city{i % 50}\n")
    size = src.stat().st_size

    tracemalloc.start()
    convert(src, tmp_path / "big.json")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < size / 8
    data = json.loads((tmp_path / "big.json").read_text(encoding="utf-8"))
    assert len(data) == rows
    assert data[-1]["id"] == str(rows - 1)


# --- json -> csv -----------------------------------------------------------

def test_json_to_csv_basic(tmp_path):
    out = to_csv(tmp_path, '[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]')
    assert out.splitlines() == ["a,b", "1,x", "2,y"]


def test_json_to_csv_uses_union_of_keys_and_fills_gaps(tmp_path):
    out = to_csv(tmp_path, '[{"a": 1}, {"b": 2, "a": 3}]')
    assert out.splitlines() == ["a,b", "1,", "3,2"]


def test_json_to_csv_scalars(tmp_path):
    out = to_csv(tmp_path, '[{"n": null, "t": true, "f": false, "x": 1.5}]')
    assert out.splitlines() == ["n,t,f,x", ",true,false,1.5"]


def test_json_to_csv_delimiter_and_unicode(tmp_path):
    out = to_csv(tmp_path, '[{"nombre": "Niño", "n": 1}]', delimiter=";")
    assert out.splitlines() == ["nombre;n", "Niño;1"]


def test_json_to_csv_accepts_bom(tmp_path):
    out = to_csv(tmp_path, b'\xef\xbb\xbf[{"a": 1}]')
    assert out.splitlines() == ["a", "1"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"a": 1}', "list of objects"),
        ("[]", "list of objects"),
        ("[1, 2]", "Item 1 is not an object"),
        ('[{"a": 1}, {"a": {"b": 2}}]', "Item 2 has nested data in 'a'"),
        ('[{"a": [1]}]', "nested data"),
        ("[{}]", "no fields"),
        ("not json", "not valid JSON"),
        (b'[{"a": "\xe9"}]', "not valid JSON"),
    ],
)
def test_json_to_csv_invalid_files(tmp_path, content, message):
    src = make(tmp_path, "in.json", content)
    with pytest.raises(InvalidFileError, match=message):
        convert(src, tmp_path / "out.csv")
    assert leftovers(tmp_path) == ["in.json"]


def test_csv_json_csv_roundtrip_preserves_tricky_fields(tmp_path):
    original = 'a,b\r\n"x, ""y""","line1\nline2"\r\nplain,ñ\r\n'
    as_json = make(tmp_path, "mid.json", to_json(tmp_path, original))
    back = tmp_path / "back.csv"
    convert(as_json, back)
    assert back.read_bytes().decode("utf-8") == original


# --- json -> txt -------------------------------------------------------------

def test_json_to_txt_is_indented_and_keeps_unicode(tmp_path):
    src = make(tmp_path, "in.json", '{"name":"Niño","tags":[1,2]}')
    out = tmp_path / "out.txt"
    convert(src, out)
    text = out.read_text(encoding="utf-8")
    assert text == '{\n  "name": "Niño",\n  "tags": [\n    1,\n    2\n  ]\n}\n'


def test_json_to_txt_accepts_any_json_value(tmp_path):
    src = make(tmp_path, "in.json", "5")
    out = tmp_path / "out.txt"
    convert(src, out)
    assert out.read_text(encoding="utf-8") == "5\n"


def test_json_to_txt_invalid_json(tmp_path):
    src = make(tmp_path, "in.json", "{oops")
    with pytest.raises(InvalidFileError, match="not valid JSON"):
        convert(src, tmp_path / "out.txt")
    assert leftovers(tmp_path) == ["in.json"]
