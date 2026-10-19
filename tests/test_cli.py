import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lfconv import describe_converters
from lfconv.core import batch
from lfconv.cli.main import main

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def run(capsys, *args):
    code = main([str(a) for a in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def events(out):
    return [json.loads(line) for line in out.splitlines()]


def write_csv(path, rows="a,b\n1,2\n"):
    path.write_text(rows, encoding="utf-8")
    return path


# --- information ----------------------------------------------------------------

def test_version(capsys):
    code, out, _ = run(capsys, "--version")
    assert code == 0 and out.startswith("lfconv ")


def test_list_human_and_json(capsys):
    code, out, _ = run(capsys, "--list")
    assert code == 0
    assert "csv" in out and "-> json" in out
    code, out, _ = run(capsys, "--list", "--json")
    data = json.loads(out)
    assert code == 0 and {"source": "csv", "target": "json"}.items() <= data[0].items()
    assert data == json.loads(json.dumps(describe_converters()))


def test_help_shows_format_options_only_with_a_target(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
    assert "--quality" not in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main(["--to", "webp", "--help"])
    assert info.value.code == 0
    assert "--quality" in capsys.readouterr().out


def test_no_registered_option_collides_with_a_fixed_flag():
    reserved = {"to", "output", "overwrite", "json", "verbose", "list", "version", "help"}
    for conversion in describe_converters():
        for option in conversion["options"]:
            assert option["name"].replace("_", "-") not in reserved


# --- converting files --------------------------------------------------------------

def test_single_file_is_written_next_to_the_input(tmp_path, capsys):
    src = write_csv(tmp_path / "data.csv")
    code, out, err = run(capsys, src, "--to", "json")
    assert code == 0 and err == ""
    assert (tmp_path / "data.json").exists()
    assert out.startswith("OK") and "Done" not in out


def test_output_folder_is_created(tmp_path, capsys):
    src = write_csv(tmp_path / "data.csv")
    code, _, _ = run(capsys, src, "--to", "json", "-o", tmp_path / "new" / "dir")
    assert code == 0 and (tmp_path / "new" / "dir" / "data.json").exists()


def test_target_aliases_are_normalized(tmp_path, capsys):
    pytest.importorskip("PIL")
    from PIL import Image

    Image.new("RGB", (8, 8)).save(tmp_path / "p.png")
    code, _, _ = run(capsys, tmp_path / "p.png", "--to", "JPEG")
    assert code == 0 and (tmp_path / "p.jpg").exists()


def test_folder_converts_matching_files_only(tmp_path, capsys):
    folder = tmp_path / "in"
    folder.mkdir()
    write_csv(folder / "b.csv")
    write_csv(folder / "a.csv")
    (folder / "notes.txt").write_text("hi", encoding="utf-8")
    write_csv(folder / ".hidden.csv")
    (folder / "sub").mkdir()
    write_csv(folder / "sub" / "deep.csv")
    code, out, err = run(capsys, folder, "--to", "json", "-o", tmp_path / "out")
    assert code == 0 and err == ""
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["a.json", "b.json"]
    assert out.index("a.csv") < out.index("b.csv")
    assert "Done: 2 converted, 0 failed, 1 skipped." in out


def test_folder_without_convertible_files_is_a_usage_error(tmp_path, capsys):
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    code, _, err = run(capsys, tmp_path, "--to", "json")
    assert code == 2 and "no files to convert" in err


def test_one_failure_does_not_stop_the_batch(tmp_path, capsys):
    good = write_csv(tmp_path / "good.csv")
    bad = write_csv(tmp_path / "bad.csv", "a,b\n1\n")
    code, out, err = run(capsys, bad, good, "--to", "json")
    assert code == 1
    assert (tmp_path / "good.json").exists() and not (tmp_path / "bad.json").exists()
    assert "FAIL" in err and "bad.csv" in err
    assert "Done: 1 converted, 1 failed." in out


def test_missing_input_fails_cleanly(tmp_path, capsys):
    code, _, err = run(capsys, tmp_path / "nope.csv", "--to", "json")
    assert code == 1 and "not found" in err and "Traceback" not in err


def test_existing_output_needs_overwrite(tmp_path, capsys):
    src = write_csv(tmp_path / "data.csv")
    (tmp_path / "data.json").write_text("old", encoding="utf-8")
    code, _, err = run(capsys, src, "--to", "json")
    assert code == 1 and "already exists" in err
    assert (tmp_path / "data.json").read_text(encoding="utf-8") == "old"
    code, _, _ = run(capsys, src, "--to", "json", "--overwrite")
    assert code == 0 and (tmp_path / "data.json").read_text(encoding="utf-8") != "old"


def test_two_inputs_with_the_same_output_name_never_overwrite_each_other(tmp_path, capsys):
    pytest.importorskip("PIL")
    from PIL import Image

    Image.new("RGB", (8, 8), "red").save(tmp_path / "a.png")
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "a.webp")
    code, _, err = run(capsys, tmp_path / "a.png", tmp_path / "a.webp", "--to", "jpg", "--overwrite")
    assert code == 1 and "Another input" in err
    with Image.open(tmp_path / "a.jpg") as img:
        assert img.convert("RGB").getpixel((2, 2))[0] > 200  # the first (red) one


# --- usage errors ------------------------------------------------------------------

@pytest.mark.parametrize(
    "args",
    [[], ["--to", "json"], ["--to", "xyz", "x.csv"], ["x.csv"]],
)
def test_usage_errors_exit_with_2(capsys, args):
    code, _, err = run(capsys, *args)
    assert code == 2 and err.startswith("lfconv: error:")


def test_unsupported_target_lists_the_available_ones(capsys):
    _, _, err = run(capsys, "x.csv", "--to", "xyz")
    assert "Available:" in err and "json" in err


def test_output_that_is_a_file_is_a_usage_error(tmp_path, capsys):
    src = write_csv(tmp_path / "data.csv")
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    code, _, err = run(capsys, src, "--to", "json", "-o", blocker)
    assert code == 2 and "not a folder" in err


# --- format options ----------------------------------------------------------------

def test_options_are_passed_to_the_converter(tmp_path, capsys):
    pytest.importorskip("PIL")
    from PIL import Image

    data = os.urandom(96 * 96 * 3)
    Image.frombytes("RGB", (96, 96), data).save(tmp_path / "n.png")
    run(capsys, tmp_path / "n.png", "--to", "jpg", "--quality", 10, "-o", tmp_path / "low")
    run(capsys, tmp_path / "n.png", "--to", "jpg", "--quality", 95, "-o", tmp_path / "high")
    assert (tmp_path / "low" / "n.jpg").stat().st_size < (tmp_path / "high" / "n.jpg").stat().st_size


def test_invalid_option_values_are_rejected_before_converting(tmp_path, capsys):
    pytest.importorskip("PIL")
    from PIL import Image

    Image.new("RGB", (8, 8)).save(tmp_path / "p.png")
    code, _, err = run(capsys, tmp_path / "p.png", "--to", "jpg", "--quality", 500)
    assert code == 2 and "quality" in err and "at most 100" in err
    assert not (tmp_path / "p.jpg").exists()


def test_flags_of_other_formats_do_not_exist(tmp_path, capsys):
    src = write_csv(tmp_path / "data.csv")
    with pytest.raises(SystemExit) as info:
        main([str(src), "--to", "json", "--quality", "50"])
    assert info.value.code == 2
    capsys.readouterr()


def test_option_that_applies_to_no_input_is_a_usage_error(tmp_path, capsys):
    (tmp_path / "t.txt").write_text("hi", encoding="utf-8")
    code, _, err = run(capsys, tmp_path / "t.txt", "--to", "pdf", "--quality", 50)
    assert code == 2 and "'quality' does not apply" in err


def test_option_only_reaches_converters_that_declare_it(tmp_path, capsys):
    pytest.importorskip("PIL")
    from PIL import Image

    Image.new("RGB", (8, 8)).save(tmp_path / "p.png")
    (tmp_path / "t.txt").write_text("hi", encoding="utf-8")
    code, _, err = run(capsys, tmp_path / "p.png", tmp_path / "t.txt", "--to", "pdf", "--quality", 50)
    assert code == 0 and err == ""


def test_delimiter_accepts_the_word_tab(tmp_path, capsys):
    src = write_csv(tmp_path / "t.csv", "a\tb\n1\t2\n")
    code, _, _ = run(capsys, src, "--to", "json", "--delimiter", "tab")
    assert code == 0
    assert json.loads((tmp_path / "t.json").read_text(encoding="utf-8")) == [{"a": "1", "b": "2"}]


# --- --json ----------------------------------------------------------------------------

def test_json_lines_for_a_mixed_batch(tmp_path, capsys):
    folder = tmp_path / "in"
    folder.mkdir()
    write_csv(folder / "ñandú.csv")
    write_csv(folder / "bad.csv", "a,b\n1\n")
    (folder / "notes.txt").write_text("hi", encoding="utf-8")
    code, out, err = run(capsys, folder, "--to", "json", "--json")
    assert code == 1 and err == ""
    assert out.isascii()
    got = events(out)
    assert [e["event"] for e in got] == ["skipped", "failed", "converted", "summary"]
    failed, converted = got[1], got[2]
    assert failed["error"]["code"] == "invalid_file" and failed["index"] == 1 and failed["total"] == 2
    assert converted["input"].endswith("ñandú.csv") and converted["output"].endswith("ñandú.json")
    assert got[3] == {"event": "summary", "converted": 1, "failed": 1, "skipped": 1, "interrupted": False}


def test_json_usage_errors_are_events(capsys):
    code, out, err = run(capsys, "x.csv", "--to", "xyz", "--json")
    assert code == 2 and err == ""
    assert events(out)[0]["error"]["code"] == "usage"


# --- verbose, crashes, interrupts -------------------------------------------------

def test_verbose_shows_technical_details_only_when_asked(tmp_path, capsys):
    bad = write_csv(tmp_path / "bad.csv", "a,b\n1\n")
    _, _, quiet = run(capsys, bad, "--to", "json")
    assert "Traceback" not in quiet
    _, out, loud = run(capsys, bad, "--to", "json", "--verbose")
    assert "Traceback" in loud and "InvalidFileError" in loud


def test_verbose_shows_timings(tmp_path, capsys):
    src = write_csv(tmp_path / "data.csv")
    _, out, _ = run(capsys, src, "--to", "json", "-v")
    assert out.rstrip().endswith("s)")


def test_unexpected_errors_are_reported_without_a_traceback(tmp_path, capsys, monkeypatch):
    src = write_csv(tmp_path / "data.csv")

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(batch, "convert", explode)
    code, _, err = run(capsys, src, "--to", "json")
    assert code == 1 and "Unexpected error" in err and "boom" not in err
    code, out, _ = run(capsys, src, "--to", "json", "--json")
    assert events(out)[0]["error"]["code"] == "internal_error"


def test_ctrl_c_stops_cleanly_with_a_summary(tmp_path, capsys, monkeypatch):
    first, second = write_csv(tmp_path / "a.csv"), write_csv(tmp_path / "b.csv")
    real_convert = batch.convert
    calls = []

    def interrupt_second(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real_convert(*args, **kwargs)

    monkeypatch.setattr(batch, "convert", interrupt_second)
    code, out, err = run(capsys, first, second, "--to", "json")
    assert code == 130 and "Interrupted" in err
    assert "Done: 1 converted, 0 failed." in out
    assert (tmp_path / "a.json").exists() and not (tmp_path / "b.json").exists()


# --- process level ---------------------------------------------------------------------

def python(code_or_args, tmp_path, *, c=False):
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    args = [sys.executable, "-c" if c else "-m", *code_or_args] if c else [sys.executable, "-m", *code_or_args]
    return subprocess.run(args, capture_output=True, text=True, cwd=tmp_path, env=env, timeout=60)


def test_python_dash_m_entry_point(tmp_path):
    write_csv(tmp_path / "data.csv")
    result = python(["lfconv", "data.csv", "--to", "json"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data.json").exists()


def test_startup_does_not_import_heavy_modules(tmp_path):
    snippet = (
        "import sys\n"
        "from lfconv.cli.main import main\n"
        "try:\n    main(['--to', 'webp', '--help'])\nexcept SystemExit:\n    pass\n"
        "print('PIL' in sys.modules)\n"
    )
    result = python([snippet], tmp_path, c=True)
    assert result.stdout.strip().endswith("False"), result.stderr
