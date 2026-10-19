import gc
import time

import pytest

tk = pytest.importorskip("tkinter")

from lfconv import register_converter  # noqa: E402
from lfconv.converters import load_builtin_converters  # noqa: E402
from lfconv.gui import app as app_module  # noqa: E402
from lfconv.gui import messages  # noqa: E402

PIL = pytest.importorskip("PIL")


class FakeMessageBox:
    """Dialogs that would block the test are recorded instead."""

    def __init__(self):
        self.calls = []
        self.answer = True

    def showerror(self, title, message, **kwargs):
        self.calls.append(("error", message))

    def showwarning(self, title, message, **kwargs):
        self.calls.append(("warning", message))

    def askyesno(self, title, message, **kwargs):
        self.calls.append(("ask", message))
        return self.answer


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available (run with xvfb-run on a headless machine)")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass
    gc.collect()  # free Tk variables on this thread, never on a worker thread


@pytest.fixture
def box(monkeypatch):
    fake = FakeMessageBox()
    monkeypatch.setattr(app_module, "messagebox", fake)
    return fake


@pytest.fixture
def app(root, box):
    load_builtin_converters()
    return app_module.App(root)


def touch(folder, name, text="a,b\n1,2\n"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def png(folder, name="p.png"):
    from PIL import Image

    path = folder / name
    Image.new("RGB", (8, 8), "red").save(path)
    return path


def wait_idle(root, app, timeout=15):
    deadline = time.monotonic() + timeout
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not app.busy, "conversion did not finish"


def rows(app):
    return [app._tree.item(row, "values") for row in app._tree.get_children()]


def window_exists(root):
    try:
        return bool(root.winfo_exists())
    except tk.TclError:  # destroyed
        return False


def disabled(widget):
    return "disabled" in widget.state()


# --- empty and loaded states -------------------------------------------------------------

def test_starts_empty_with_a_hint_and_nothing_to_press(app):
    assert app.message == messages.HINT_EMPTY
    assert rows(app) == [] and disabled(app._convert_button)
    assert app._target_box.get() == ""
    assert not app._options_panel.has_options


def test_adding_files_shows_them_with_type_and_offers_targets(app, tmp_path):
    app.add_paths([touch(tmp_path, "a.csv"), touch(tmp_path, "b.csv"), touch(tmp_path, "x.docx", "x")])
    assert [r[:2] for r in rows(app)] == [("a.csv", "CSV"), ("b.csv", "CSV")]
    assert app._target_box.get() == "JSON"
    assert not disabled(app._convert_button)
    assert app.message == "2 files added, 1 not supported."


def test_remove_and_clear(app, tmp_path):
    app.add_paths([touch(tmp_path, "a.csv"), touch(tmp_path, "b.csv"), touch(tmp_path, "c.csv")])
    first = app._tree.get_children()[0]
    app._tree.selection_set(first)
    app._remove_selected()
    assert [r[0] for r in rows(app)] == ["b.csv", "c.csv"]
    app._clear()
    assert rows(app) == [] and app.message == messages.HINT_EMPTY and disabled(app._convert_button)


# --- converting ----------------------------------------------------------------------------

def test_converts_a_batch_and_reports_per_file(root, app, tmp_path, box):
    app.add_paths([touch(tmp_path, "a.csv"), touch(tmp_path, "b.csv")])
    app.start()
    assert app.busy
    wait_idle(root, app)
    assert (tmp_path / "a.json").exists() and (tmp_path / "b.json").exists()
    assert [r[2] for r in rows(app)] == ["Done: a.json", "Done: b.json"]
    assert app.message == "All 2 files converted."
    assert box.calls == []
    assert not disabled(app._convert_button) and not disabled(app._add_files_button)
    assert float(app._progress["value"]) == 2.0


def test_window_stays_responsive_while_converting(root, app, tmp_path):
    def slow(src, dst, options):
        time.sleep(0.5)
        dst.write_text("done", encoding="utf-8")

    register_converter("csv", "slow", slow)
    app.add_paths([touch(tmp_path, "a.csv")])
    app.set_target("slow")

    started = time.perf_counter()
    app.start()
    assert time.perf_counter() - started < 0.2  # start() does not wait for the conversion
    assert app.busy
    for widget in (app._convert_button, app._add_files_button, app._target_box, app._clear_button):
        assert disabled(widget)
    assert rows(app)[0][2] == "" or rows(app)[0][2] == messages.STATUS_CONVERTING

    updates = 0
    while app.busy:
        root.update()  # the event loop keeps running during the conversion
        updates += 1
        time.sleep(0.01)
    assert updates > 5
    assert (tmp_path / "a.slow").exists()
    assert app.message == "File converted."


def test_failures_are_explained_in_the_row_and_in_one_dialog(root, app, tmp_path, box):
    app.add_paths([touch(tmp_path, "bad.csv", "a,b\n1\n"), touch(tmp_path, "good.csv")])
    app.start()
    wait_idle(root, app)
    bad, good = rows(app)
    assert "columns" in bad[2] and good[2] == "Done: good.json"
    assert app.message == "1 converted, 1 failed."
    assert [kind for kind, _ in box.calls] == ["warning"]
    assert "bad.csv" in box.calls[0][1] and "Traceback" not in box.calls[0][1]

    app._tree.selection_set(app._tree.get_children()[0])
    app._row_selected()
    assert app._detail.cget("text").startswith(messages.FAILED_TITLE)


def test_unexpected_errors_never_show_technical_text(root, app, tmp_path, box, monkeypatch, capsys):
    from lfconv.core import batch

    monkeypatch.setattr(batch, "convert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    app.add_paths([touch(tmp_path, "a.csv")])
    app.start()
    wait_idle(root, app)
    assert rows(app)[0][2] == messages.INTERNAL_ERROR
    assert "boom" not in box.calls[0][1]


def test_output_folder_and_overwrite(root, app, tmp_path, box):
    src = touch(tmp_path, "a.csv")
    out = tmp_path / "results"
    app.add_paths([src])
    app.set_output_dir(out)
    assert str(out) in app._out_label.cget("text") or app._out_label.cget("text").endswith("results")
    app.start()
    wait_idle(root, app)
    assert (out / "a.json").exists() and not (tmp_path / "a.json").exists()

    app.start()  # same output again: refused without "replace"
    wait_idle(root, app)
    assert "already exists" in rows(app)[0][2]
    app._overwrite_var.set(True)
    box.calls.clear()
    app.start()
    wait_idle(root, app)
    assert rows(app)[0][2] == "Done: a.json" and box.calls == []
    app.set_output_dir(None)
    assert app._out_label.cget("text") == messages.SAME_FOLDER


# --- targets and options -----------------------------------------------------------------------

def test_mixed_list_offers_every_target_and_marks_what_cannot_be_converted(root, app, tmp_path, box):
    app.add_paths([png(tmp_path), touch(tmp_path, "d.csv")])
    assert list(app._target_box["values"]) == ["JPG", "JSON", "PDF", "WebP"]
    app.set_target("json")
    assert rows(app)[0][2] == "Cannot convert to JSON" and rows(app)[1][2] == ""
    app.start()
    wait_idle(root, app)
    assert (tmp_path / "d.json").exists() and not (tmp_path / "p.json").exists()
    assert rows(app)[0][2] == "Cannot convert to JSON"
    assert app.message == "File converted."


def test_options_panel_follows_the_target_and_remembers_values(app, tmp_path):
    app.add_paths([png(tmp_path)])
    app.set_target("jpg")
    assert app._options_panel.has_options and app._options_panel.values() == {"quality": 85}
    app._options_panel._vars["quality"].set("40")
    app.set_target("webp")
    assert app._options_panel.values() == {"quality": 40}
    app.add_paths([touch(tmp_path, "t.txt", "hi")])
    app.set_target("pdf")
    assert app._options_panel.values() == {"quality": 40, "page_size": "a4", "font_size": 10}


def test_panel_is_shown_only_when_there_are_options(app, tmp_path):
    app.add_paths([touch(tmp_path, "d.json", "[]")])
    app.set_target("txt")
    assert not app._options_panel.has_options
    assert app._options_panel.grid_info() == {}  # removed from the layout
    app.set_target("csv")
    assert app._options_panel.has_options and app._options_panel.grid_info()


def test_invalid_option_is_reported_before_anything_runs(app, tmp_path, box):
    app.add_paths([png(tmp_path)])
    app.set_target("jpg")
    for text, expected in (("500", "at most 100"), ("abc", "whole number")):
        app._options_panel._vars["quality"].set(text)
        app.start()
        assert not app.busy and expected in box.calls[-1][1]
    assert not (tmp_path / "p.jpg").exists()


def test_option_values_are_used_by_the_conversion(root, app, tmp_path):
    from PIL import Image
    import os

    Image.frombytes("RGB", (96, 96), os.urandom(96 * 96 * 3)).save(tmp_path / "n.png")
    app.add_paths([tmp_path / "n.png"])
    app.set_target("jpg")
    sizes = {}
    for quality in ("10", "95"):
        app.set_output_dir(tmp_path / quality)
        app._options_panel._vars["quality"].set(quality)
        app.start()
        wait_idle(root, app)
        sizes[quality] = (tmp_path / quality / "n.jpg").stat().st_size
    assert sizes["10"] < sizes["95"]


def test_delimiter_choice_includes_tab(app, tmp_path):
    app.add_paths([touch(tmp_path, "d.json", "[]")])
    app.set_target("csv")
    assert "tab" in app._options_panel.winfo_children()[1]["values"]


# --- closing ------------------------------------------------------------------------------------

def test_closing_an_idle_window_just_closes(root, app, box):
    app._on_close()
    assert box.calls == []
    assert not window_exists(root)


def test_closing_while_converting_asks_then_stops_after_the_current_file(root, app, tmp_path, box):
    def slow(src, dst, options):
        time.sleep(0.3)
        dst.write_text("done", encoding="utf-8")

    register_converter("csv", "slow", slow)
    app.add_paths([touch(tmp_path, f"{n}.csv") for n in "abc"])
    app.set_target("slow")
    app.start()

    box.answer = False
    app._on_close()
    assert app.busy and not app._closing  # user said no: keep going

    box.answer = True
    app._on_close()
    assert app._closing and app.message == messages.STOPPING
    deadline = time.monotonic() + 15
    while window_exists(root) and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not window_exists(root), "window did not close after the worker finished"
    assert (tmp_path / "a.slow").exists() and not (tmp_path / "c.slow").exists()


def test_file_dialog_filter_covers_aliases_and_uppercase():
    load_builtin_converters()
    patterns = app_module._file_types()[0][1].split()
    for expected in ("*.png", "*.PNG", "*.jpeg", "*.JPG", "*.csv", "*.webp"):
        assert expected in patterns


def test_attributes_do_not_replace_tkinter_methods(app):
    """Widgets inherit from tkinter classes: an attribute named like one of its methods
    (e.g. ``self._options``) breaks Tk itself."""
    for widget in (app, app._options_panel):
        clashes = [name for name in vars(widget) if callable(getattr(tk.Misc, name, None))]
        assert clashes == [], clashes
