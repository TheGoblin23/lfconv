import time

import pytest

from lfconv import register_converter
from lfconv.converters import load_builtin_converters
from lfconv.core import batch
from lfconv.core.batch import plan_jobs
from lfconv.gui import messages
from lfconv.gui.model import PlanError, Selection
from lfconv.gui.worker import BatchWorker, Converted, Failed, Finished, Started

PIL = pytest.importorskip("PIL")


@pytest.fixture(autouse=True)
def builtin():
    load_builtin_converters()


def touch(folder, name, text="a,b\n1,2\n"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def png(folder, name="p.png"):
    from PIL import Image

    path = folder / name
    Image.new("RGB", (8, 8), "red").save(path)
    return path


# --- Selection ---------------------------------------------------------------

def test_add_files_folders_duplicates_and_unsupported(tmp_path):
    a = touch(tmp_path, "a.csv")
    touch(tmp_path, "b.csv")
    touch(tmp_path, "notes.docx", "x")
    touch(tmp_path, ".hidden.csv")
    (tmp_path / "sub").mkdir()
    touch(tmp_path / "sub", "deep.csv")

    selection = Selection()
    summary = selection.add([a])
    assert (summary.added, summary.unsupported, summary.duplicates) == (1, 0, 0)
    summary = selection.add([tmp_path, a, tmp_path / "missing.csv"])
    assert (summary.added, summary.unsupported, summary.duplicates) == (1, 1, 2)
    assert [e.path.name for e in selection.entries] == ["a.csv", "b.csv"]
    assert [e.format for e in selection.entries] == ["csv", "csv"]


def test_remove_and_clear_allow_adding_again(tmp_path):
    a, b = touch(tmp_path, "a.csv"), touch(tmp_path, "b.csv")
    selection = Selection()
    selection.add([a, b])
    selection.remove([0])
    assert [e.path.name for e in selection.entries] == ["b.csv"]
    assert selection.add([a]).added == 1
    selection.clear()
    assert selection.entries == [] and selection.add([a]).added == 1


def test_targets_and_default_target(tmp_path):
    selection = Selection()
    assert selection.available_targets() == [] and selection.default_target() is None
    selection.add([png(tmp_path)])
    assert selection.available_targets() == ["jpg", "pdf", "webp"]
    assert selection.default_target() == "jpg"
    selection.add([touch(tmp_path, "d.csv")])
    assert selection.available_targets() == ["jpg", "json", "pdf", "webp"]
    assert selection.default_target() == "jpg"  # nothing common: first available


def test_default_target_prefers_one_every_file_can_reach(tmp_path):
    selection = Selection()
    selection.add([touch(tmp_path, "d.json", "[]")])  # json -> csv, txt
    selection.add([touch(tmp_path, "d.csv")])  # csv -> json
    assert selection.default_target() == "csv"
    selection.add([tmp_path / "d.json"])
    assert selection.default_target() == "csv"


def test_options_follow_the_files_that_can_be_converted(tmp_path):
    selection = Selection()
    selection.add([touch(tmp_path, "t.txt", "hi")])
    assert [o.name for o in selection.options_for("pdf")] == ["page_size", "font_size"]
    selection.add([png(tmp_path)])
    assert [o.name for o in selection.options_for("pdf")] == ["quality", "page_size", "font_size"]
    assert [o.name for o in selection.options_for("jpg")] == ["quality"]
    assert selection.options_for("json") == []


def test_plan_separates_what_cannot_be_converted(tmp_path):
    selection = Selection()
    selection.add([png(tmp_path), touch(tmp_path, "d.csv")])
    plan = selection.plan("json", None, {})
    assert [job.src.name for job in plan.jobs] == ["d.csv"]
    assert [e.path.name for e in plan.skipped] == ["p.png"]


def test_plan_errors_are_user_readable(tmp_path):
    selection = Selection()
    selection.add([png(tmp_path)])
    with pytest.raises(PlanError, match="JSON"):
        selection.plan("json", None, {})
    with pytest.raises(PlanError, match="at most 100"):
        selection.plan("jpg", None, {"quality": 500})
    with pytest.raises(PlanError, match="whole number"):
        selection.plan("jpg", None, {"quality": "abc"})


# --- BatchWorker ---------------------------------------------------------------

def collect(worker, timeout=15):
    worker.start()
    events, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        events += worker.poll()
        if events and isinstance(events[-1], Finished):
            return events
        time.sleep(0.01)
    raise AssertionError("worker did not finish")


def jobs_for(tmp_path, *names, target="json"):
    paths = [touch(tmp_path, name, "a,b\n1,2\n" if name.endswith("ok.csv") else "a,b\n1\n") for name in names]
    jobs, _ = plan_jobs(paths, target)
    return jobs


def test_worker_reports_every_step_in_order(tmp_path):
    jobs = jobs_for(tmp_path, "1ok.csv", "2ok.csv")
    worker = BatchWorker(jobs, "json", {})
    assert worker.poll() == []
    events = collect(worker)
    assert [type(e) for e in events] == [Started, Converted, Started, Converted, Finished]
    assert [e.index for e in events[:2]] == [1, 1] and events[0].total == 2
    assert events[-1] == Finished(converted=2, failed=0, stopped=False)
    assert (tmp_path / "1ok.json").exists() and (tmp_path / "2ok.json").exists()


def test_worker_continues_after_a_failure(tmp_path):
    events = collect(BatchWorker(jobs_for(tmp_path, "bad.csv", "good_ok.csv"), "json", {}))
    failed = [e for e in events if isinstance(e, Failed)]
    assert len(failed) == 1 and failed[0].job.src.name == "bad.csv"
    assert messages.failure_reason(failed[0].error)
    assert events[-1] == Finished(converted=1, failed=1, stopped=False)


def test_worker_stop_finishes_the_current_file_only(tmp_path):
    def slow(src, dst, options):
        time.sleep(0.3)
        dst.write_text("done", encoding="utf-8")

    register_converter("csv", "slow", slow, replace=True)
    jobs, _ = plan_jobs([touch(tmp_path, f"{n}.csv") for n in "abc"], "slow")
    worker = BatchWorker(jobs, "slow", {})
    worker.start()
    events = []
    while not any(isinstance(e, Started) for e in events):
        events += worker.poll()
        time.sleep(0.005)
    worker.stop()
    while not isinstance(events[-1], Finished):
        events += worker.poll()
        time.sleep(0.01)
    assert events[-1] == Finished(converted=1, failed=0, stopped=True)
    assert (tmp_path / "a.slow").exists() and not (tmp_path / "b.slow").exists()


def test_unexpected_errors_are_reported_and_logged(tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(batch, "convert", explode)
    events = collect(BatchWorker(jobs_for(tmp_path, "x_ok.csv"), "json", {}))
    failed = next(e for e in events if isinstance(e, Failed))
    assert messages.failure_reason(failed.error) == messages.INTERNAL_ERROR
    assert "boom" in capsys.readouterr().err  # kept for whoever runs the app from a terminal


def test_poll_never_blocks(tmp_path):
    worker = BatchWorker([], "json", {})
    started = time.perf_counter()
    for _ in range(1000):
        worker.poll()
    assert time.perf_counter() - started < 0.5


# --- messages -------------------------------------------------------------------

def test_messages():
    assert messages.files(1) == "1 file" and messages.files(3) == "3 files"
    assert messages.format_name("webp") == "WebP" and messages.format_name("xyz") == "XYZ"
    assert messages.option_name("page_size") == "Page size" and messages.option_name("quality") == "Quality"
    assert messages.finished(3, 0, False, 3) == "All 3 files converted."
    assert messages.finished(1, 0, False, 1) == "File converted."
    assert messages.finished(2, 1, False, 3) == "2 converted, 1 failed."
    assert messages.finished(1, 0, True, 4) == "Stopped: 1 of 4 converted."
    assert messages.added(2, 1, 1) == "2 files added, 1 not supported, 1 already in the list."
