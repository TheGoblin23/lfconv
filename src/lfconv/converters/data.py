import csv
import json
from pathlib import Path
from typing import Any, Iterator

from ..core.errors import InvalidFileError
from ..core.options import Option
from ..core.registry import register_converter

_SAMPLE_SIZE = 64 * 1024
_DELIMITERS = (",", ";", "\t", "|")

_CSV_TO_JSON_OPTIONS = (
    Option("delimiter", "str", "auto", "Field separator; 'auto' detects it.",
           choices=("auto", *_DELIMITERS)),
)
_JSON_TO_CSV_OPTIONS = (
    Option("delimiter", "str", ",", "Field separator.", choices=_DELIMITERS),
)


def register() -> None:
    register_converter("csv", "json", csv_to_json, _CSV_TO_JSON_OPTIONS, replace=True)
    register_converter("json", "csv", json_to_csv, _JSON_TO_CSV_OPTIONS, replace=True)
    register_converter("json", "txt", json_to_txt, replace=True)


def csv_to_json(src: Path, dst: Path, options: dict[str, Any]) -> None:
    """Stream a CSV file into a JSON array of objects, one row per line.

    All values stay strings: no type guessing.
    """
    try:
        delimiter = options["delimiter"]
        if delimiter == "auto":
            delimiter = _sniff_delimiter(src)
        with src.open(encoding="utf-8-sig", newline="") as fin, \
                dst.open("w", encoding="utf-8") as fout:
            rows = csv.reader(fin, delimiter=delimiter)
            header = _read_header(rows)
            fout.write("[")
            first = True
            for record in _records(rows, header):
                fout.write(("\n  " if first else ",\n  ") + json.dumps(record, ensure_ascii=False))
                first = False
            fout.write("]\n" if first else "\n]\n")
    except (UnicodeDecodeError, csv.Error) as exc:
        raise InvalidFileError("The file is not a valid CSV text file.") from exc


def json_to_csv(src: Path, dst: Path, options: dict[str, Any]) -> None:
    """Write a JSON array of flat objects as CSV (the JSON is loaded in memory)."""
    records = _as_records(_load_json(src))
    columns = list(dict.fromkeys(key for record in records for key in record))
    if not columns:
        raise InvalidFileError("The JSON objects have no fields.")
    with dst.open("w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=columns, delimiter=options["delimiter"])
        writer.writeheader()
        for record in records:
            writer.writerow({key: _cell(value) for key, value in record.items()})


def json_to_txt(src: Path, dst: Path, options: dict[str, Any]) -> None:
    """Write the JSON document pretty-printed (the JSON is loaded in memory)."""
    data = _load_json(src)
    with dst.open("w", encoding="utf-8") as fout:
        json.dump(data, fout, indent=2, ensure_ascii=False)
        fout.write("\n")


def _sniff_delimiter(src: Path) -> str:
    with src.open(encoding="utf-8-sig", newline="") as fin:
        sample = fin.read(_SAMPLE_SIZE)
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS)).delimiter
    except csv.Error:
        return ","


def _read_header(rows: Iterator[list[str]]) -> list[str]:
    for row in rows:
        if row:
            if len(set(row)) != len(row):
                raise InvalidFileError("The CSV header has duplicate column names.")
            return row
    raise InvalidFileError("The CSV file has no header row.")


def _records(rows: Any, header: list[str]) -> Iterator[dict[str, str]]:
    for row in rows:
        if not row:
            continue
        if len(row) != len(header):
            raise InvalidFileError(
                f"Line {rows.line_num} has {len(row)} columns; expected {len(header)}."
            )
        yield dict(zip(header, row))


def _load_json(src: Path) -> Any:
    try:
        with src.open(encoding="utf-8-sig") as fin:
            return json.load(fin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidFileError("The file is not valid JSON.") from exc


def _as_records(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not data:
        raise InvalidFileError("The JSON file must contain a non-empty list of objects.")
    for number, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise InvalidFileError(f"Item {number} is not an object.")
        for key, value in item.items():
            if isinstance(value, (dict, list)):
                raise InvalidFileError(
                    f"Item {number} has nested data in '{key}', which CSV cannot represent."
                )
    return data


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value
