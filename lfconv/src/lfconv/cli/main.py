import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from ..converters import load_builtin_converters
from ..core.api import describe_converters
from ..core.batch import Job, check_options, options_for_target, plan_jobs, run_job
from ..core.errors import ConverterError, UnsupportedFormatError
from ..core.formats import normalize_format
from ..core.options import Option, choice_label, choice_value

EXIT_OK = 0
EXIT_FAILED = 1  # at least one file could not be converted
EXIT_USAGE = 2  # invalid arguments or nothing to convert
EXIT_INTERRUPTED = 130


def main(argv: list[str] | None = None) -> int:
    _make_streams_safe()
    load_builtin_converters()
    conversions = describe_converters()

    # Options depend on the target format, so read --to before building the parser.
    early = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    early.add_argument("--to")
    early_args, _ = early.parse_known_args(argv)
    target = _try_normalize(early_args.to)
    option_specs = options_for_target(target) if target else []

    parser = _build_parser(option_specs)
    args = parser.parse_args(argv)

    if args.version:
        print(f"lfconv {_version()}")
        return EXIT_OK
    if args.list:
        return _print_conversions(conversions, args.json)
    return _convert_files(args, target, option_specs, conversions)


def _convert_files(
    args: argparse.Namespace,
    target: str | None,
    option_specs: list[Option],
    conversions: list[dict[str, Any]],
) -> int:
    if not args.inputs:
        return _usage_error("no input files given (see --help).", args.json)
    available = sorted({c["target"] for c in conversions})
    if not args.to:
        return _usage_error("--to is required (use --list to see what is supported).", args.json)
    if target not in available:
        return _usage_error(
            f"unsupported target format '{args.to}'. Available: {', '.join(available)}.", args.json
        )
    out_dir = Path(args.output) if args.output else None
    if out_dir is not None and out_dir.exists() and not out_dir.is_dir():
        return _usage_error(f"'{out_dir.name}' exists and is not a folder.", args.json)

    provided = {
        spec.name: choice_value(spec, getattr(args, f"opt_{spec.name}"))
        for spec in option_specs
        if hasattr(args, f"opt_{spec.name}")
    }
    jobs, skipped = plan_jobs(args.inputs, target, out_dir)
    if not jobs:
        return _usage_error("there are no files to convert.", args.json)
    problem = check_options(jobs, target, provided)
    if problem:
        return _usage_error(problem, args.json)

    reporter = Reporter(args.json, args.verbose)
    for path in skipped:
        reporter.skipped(path, target)
    converted = failed = 0
    interrupted = False
    try:
        for index, job in enumerate(jobs, start=1):
            started = time.perf_counter()
            try:
                run_job(job, target, provided, args.overwrite)
            except Exception as exc:  # one bad file must not stop the batch
                failed += 1
                reporter.failed(index, len(jobs), job, exc)
            else:
                converted += 1
                reporter.converted(index, len(jobs), job, time.perf_counter() - started)
    except KeyboardInterrupt:
        interrupted = True
    reporter.summary(converted, failed, len(skipped), interrupted, len(jobs))

    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_FAILED if failed else EXIT_OK


# --- parser -------------------------------------------------------------------

def _build_parser(option_specs: list[Option]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lfconv",
        description="Convert files locally. Nothing is uploaded; no network is used.",
        epilog="Use '--to FORMAT --help' to see the options of that output format. "
               "Exit codes: 0 ok, 1 some files failed, 2 invalid usage, 130 interrupted.",
        allow_abbrev=False,
    )
    parser.add_argument("inputs", nargs="*", metavar="INPUT", help="files or folders to convert")
    parser.add_argument("--to", metavar="FORMAT", help="output format, e.g. webp, json, pdf")
    parser.add_argument("-o", "--output", metavar="DIR",
                        help="folder for the results (default: next to each input)")
    parser.add_argument("--overwrite", action="store_true", help="replace existing output files")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON lines")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show timings and technical details of errors")
    parser.add_argument("--list", action="store_true", help="list supported conversions and exit")
    parser.add_argument("--version", action="store_true", help="show the version and exit")
    if option_specs:
        group = parser.add_argument_group("format options")
        for spec in option_specs:
            _add_option(group, spec)
    return parser


def _add_option(group: Any, spec: Option) -> None:
    detail = [f"default: {choice_label(spec.default)}"]
    if spec.choices:
        detail.append("one of: " + ", ".join(choice_label(c) for c in spec.choices))
    if spec.min is not None or spec.max is not None:
        detail.append(f"range: {spec.min:g}-{spec.max:g}" if spec.min is not None and spec.max is not None
                      else f"min: {spec.min}" if spec.min is not None else f"max: {spec.max}")
    kwargs: dict[str, Any] = {
        "dest": f"opt_{spec.name}",
        "default": argparse.SUPPRESS,
        "help": f"{spec.help} ({'; '.join(detail)})".replace("%", "%%"),
    }
    if spec.kind == "bool":
        kwargs["action"] = argparse.BooleanOptionalAction
    else:
        kwargs["type"] = {"int": int, "float": float, "str": str}[spec.kind]
        kwargs["metavar"] = spec.name.upper()
    group.add_argument("--" + spec.name.replace("_", "-"), **kwargs)


# --- output ---------------------------------------------------------------------

class Reporter:
    """Human-readable lines by default, JSON lines with --json."""

    def __init__(self, json_mode: bool, verbose: bool) -> None:
        self._json = json_mode
        self._verbose = verbose

    def converted(self, index: int, total: int, job: Job, seconds: float) -> None:
        if self._json:
            self._emit({"event": "converted", "index": index, "total": total,
                        "input": str(job.src), "output": str(job.dst)})
        else:
            timing = f" ({seconds:.2f}s)" if self._verbose else ""
            print(f"OK   {job.src} -> {job.dst}{timing}", flush=True)

    def failed(self, index: int, total: int, job: Job, exc: Exception) -> None:
        code, message = _describe_error(exc)
        if self._json:
            self._emit({"event": "failed", "index": index, "total": total,
                        "input": str(job.src), "error": {"code": code, "message": message}})
        else:
            print(f"FAIL {job.src}: {message}", file=sys.stderr, flush=True)
        if self._verbose:
            traceback.print_exception(exc, file=sys.stderr)

    def skipped(self, path: Path, target: str) -> None:
        if self._json:
            self._emit({"event": "skipped", "input": str(path), "reason": "not_convertible"})
        elif self._verbose:
            print(f"SKIP {path} (cannot convert to {target.upper()})", flush=True)

    def summary(self, converted: int, failed: int, skipped: int, interrupted: bool, total: int) -> None:
        if self._json:
            self._emit({"event": "summary", "converted": converted, "failed": failed,
                        "skipped": skipped, "interrupted": interrupted})
            return
        if interrupted:
            print("Interrupted.", file=sys.stderr, flush=True)
        if total > 1 or skipped or interrupted:
            extra = f", {skipped} skipped" if skipped else ""
            print(f"Done: {converted} converted, {failed} failed{extra}.", flush=True)

    @staticmethod
    def _emit(event: dict[str, Any]) -> None:
        print(json.dumps(event), flush=True)  # ASCII-escaped: safe on any console


def _describe_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ConverterError):
        return exc.code, str(exc)
    return "internal_error", "Unexpected error. Run with --verbose for details."


def _usage_error(message: str, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps({"event": "error", "error": {"code": "usage", "message": message}}))
    else:
        print(f"lfconv: error: {message}", file=sys.stderr)
    return EXIT_USAGE


def _print_conversions(conversions: list[dict[str, Any]], json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(conversions))
        return EXIT_OK
    targets: dict[str, list[str]] = {}
    for conversion in conversions:
        targets.setdefault(conversion["source"], []).append(conversion["target"])
    width = max((len(source) for source in targets), default=0)
    for source, reachable in targets.items():
        print(f"{source:<{width}} -> {', '.join(reachable)}")
    return EXIT_OK


def _try_normalize(name: str | None) -> str | None:
    try:
        return normalize_format(name) if name else None
    except UnsupportedFormatError:
        return None


def _make_streams_safe() -> None:
    """Never crash because a file name cannot be shown on this console."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def _version() -> str:
    from importlib import metadata

    try:
        return metadata.version("lfconv")
    except metadata.PackageNotFoundError:
        return "unknown"
