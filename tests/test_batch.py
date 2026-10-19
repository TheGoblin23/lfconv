import pytest

from lfconv import InvalidFileError, Option, OutputError, register_converter
from lfconv.core import registry as registry_module
from lfconv.core.batch import (
    Job,
    check_options,
    options_for_job,
    options_for_target,
    plan_jobs,
    run_job,
)
from lfconv.core.formats import extensions
from lfconv.core.options import choice_label, choice_value


def copy_converter(src, dst, options):
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


QUALITY = (Option("quality", "int", 85, min=1, max=100),)


@pytest.fixture
def converters():
    register_converter("aaa", "bbb", copy_converter, QUALITY)
    register_converter("ccc", "bbb", copy_converter)
    register_converter("aaa", "ddd", copy_converter)


def touch(folder, name, text="x"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


# --- planning ----------------------------------------------------------------

def test_plan_puts_outputs_next_to_inputs_or_in_the_output_folder(converters, tmp_path):
    a = touch(tmp_path, "one.aaa")
    jobs, skipped = plan_jobs([a], "bbb")
    assert jobs == [Job(a, tmp_path / "one.bbb")] and skipped == []
    jobs, _ = plan_jobs([a], "bbb", tmp_path / "out")
    assert jobs[0].dst == tmp_path / "out" / "one.bbb"


def test_plan_expands_folders_and_skips_the_rest(converters, tmp_path):
    touch(tmp_path, "b.aaa")
    touch(tmp_path, "a.ccc")
    touch(tmp_path, "notes.zzz")
    touch(tmp_path, ".hidden.aaa")
    (tmp_path / "sub").mkdir()
    touch(tmp_path / "sub", "deep.aaa")
    jobs, skipped = plan_jobs([tmp_path], "bbb")
    assert [job.src.name for job in jobs] == ["a.ccc", "b.aaa"]
    assert [path.name for path in skipped] == ["notes.zzz"]


def test_plan_keeps_explicit_files_even_if_unsupported(converters, tmp_path):
    odd = touch(tmp_path, "odd.zzz")
    jobs, skipped = plan_jobs([odd, tmp_path / "missing.aaa"], "bbb")
    assert len(jobs) == 2 and skipped == []


def test_plan_flags_inputs_that_would_write_the_same_file(converters, tmp_path):
    first, second = touch(tmp_path, "x.aaa"), touch(tmp_path, "x.ccc")
    jobs, _ = plan_jobs([first, second], "bbb")
    assert jobs[0].error is None
    assert isinstance(jobs[1].error, OutputError)


# --- options ---------------------------------------------------------------------

def test_options_for_target_is_the_union_and_can_be_restricted(converters):
    assert [o.name for o in options_for_target("bbb")] == ["quality"]
    assert options_for_target("bbb", {"ccc"}) == []
    assert options_for_target("ddd") == []
    assert options_for_target("nope") == []


def test_options_for_target_merges_choices():
    register_converter("aaa", "bbb", copy_converter, (Option("mode", "str", "x", choices=("x", "y")),))
    register_converter("ccc", "bbb", copy_converter, (Option("mode", "str", "x", choices=("x", "z")),))
    (merged,) = options_for_target("bbb")
    assert merged.choices == ("x", "y", "z") and merged.default == "x"


def test_options_for_job_keeps_only_declared_options(converters, tmp_path):
    assert options_for_job(tmp_path / "a.aaa", "bbb", {"quality": 50, "other": 1}) == {"quality": 50}
    assert options_for_job(tmp_path / "a.ccc", "bbb", {"quality": 50}) == {}
    assert options_for_job(tmp_path / "noext", "bbb", {"quality": 50}) == {}


def test_check_options(converters, tmp_path):
    jobs, _ = plan_jobs([touch(tmp_path, "a.aaa")], "bbb")
    assert check_options(jobs, "bbb", {}) is None
    assert check_options(jobs, "bbb", {"quality": 50}) is None
    assert "at most 100" in check_options(jobs, "bbb", {"quality": 500})
    only_c, _ = plan_jobs([touch(tmp_path, "a.ccc")], "bbb")
    assert "'quality' does not apply" in check_options(only_c, "bbb", {"quality": 50})


# --- running ---------------------------------------------------------------------

def test_run_job_converts_and_raises_planning_errors(converters, tmp_path):
    src = touch(tmp_path, "a.aaa", "hello")
    (job,), _ = plan_jobs([src], "bbb")
    assert run_job(job, "bbb", {}) == job.dst
    assert job.dst.read_text(encoding="utf-8") == "hello"
    with pytest.raises(OutputError):
        run_job(Job(src, job.dst, OutputError("conflict")), "bbb", {})
    with pytest.raises(OutputError, match="already exists"):
        run_job(job, "bbb", {})
    run_job(job, "bbb", {}, overwrite=True)


def test_run_job_reports_missing_files(converters, tmp_path):
    (job,), _ = plan_jobs([tmp_path / "gone.aaa"], "bbb")
    with pytest.raises(InvalidFileError):
        run_job(job, "bbb", {})


# --- small shared helpers -----------------------------------------------------------

def test_registry_infos_are_sorted(converters):
    infos = registry_module.get_registry().infos()
    assert [(i.source, i.target) for i in infos] == [("aaa", "bbb"), ("aaa", "ddd"), ("ccc", "bbb")]


def test_extensions_include_aliases():
    assert extensions("jpg") == ["jpg", "jpeg"]
    assert extensions("tiff") == ["tiff", "tif"]
    assert extensions("png") == ["png"]


def test_tab_choice_helpers():
    spec = Option("delimiter", "str", ",", choices=(",", "\t"))
    assert choice_label("\t") == "tab" and choice_label(",") == ","
    assert choice_value(spec, "tab") == "\t" and choice_value(spec, ";") == ";"
    assert choice_value(Option("x", "str", "a"), "tab") == "tab"
