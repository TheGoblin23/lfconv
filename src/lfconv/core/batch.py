"""Planning and running many conversions. Shared by the CLI and the GUI."""

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import registry
from .api import PathLike, can_convert, convert
from .errors import ConverterError, InvalidFileError, InvalidOptionError, OutputError
from .formats import format_from_path
from .options import Option, validate_options


@dataclass(frozen=True)
class Job:
    src: Path
    dst: Path
    error: ConverterError | None = None  # a problem found while planning


def plan_jobs(
    inputs: Sequence[PathLike], target: str, out_dir: Path | None = None
) -> tuple[list[Job], list[Path]]:
    """Expand folders into files and decide every output path.

    Folders are not searched recursively; hidden files and files that cannot
    be converted to ``target`` are returned as skipped. Explicit files are
    always planned, so ``convert()`` can report precisely what is wrong.
    """
    jobs: list[Job] = []
    skipped: list[Path] = []
    claimed: set[str] = set()

    def add(src: Path) -> None:
        dst = (out_dir or src.parent) / f"{src.stem}.{target}"
        key = os.path.normcase(os.path.abspath(dst))
        error = None
        if key in claimed:
            error = OutputError(f"Another input in this run already writes '{dst.name}'.")
        claimed.add(key)
        jobs.append(Job(src, dst, error))

    for raw in inputs:
        path = Path(raw)
        if not path.is_dir():
            add(path)
            continue
        try:
            children = sorted(path.iterdir())
        except OSError:
            jobs.append(Job(path, path, InvalidFileError(f"'{path.name}' cannot be read.")))
            continue
        for child in children:
            if child.name.startswith(".") or not child.is_file():
                continue
            source = format_from_path(child)
            if source and can_convert(source, target):
                add(child)
            else:
                skipped.append(child)
    return jobs, skipped


def options_for_target(target: str, sources: Iterable[str] | None = None) -> list[Option]:
    """Union of the options declared by the conversions that end in ``target``.

    Restricted to conversions starting at ``sources`` when given.
    """
    wanted = None if sources is None else set(sources)
    merged: dict[str, Option] = {}
    for info in registry.get_registry().infos():
        if info.target != target or (wanted is not None and info.source not in wanted):
            continue
        for spec in info.options:
            known = merged.get(spec.name)
            if known is None:
                merged[spec.name] = spec
            elif known.choices and spec.choices:
                extra = tuple(c for c in spec.choices if c not in known.choices)
                if extra:
                    merged[spec.name] = replace(known, choices=known.choices + extra)
    return list(merged.values())


def options_for_job(src: Path, target: str, provided: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the options this particular conversion declares."""
    source = format_from_path(src)
    if source is None or not can_convert(source, target):
        return {}
    names = {spec.name for spec in registry.get_registry().get(source, target).options}
    return {name: value for name, value in provided.items() if name in names}


def check_options(jobs: Sequence[Job], target: str, provided: Mapping[str, Any]) -> str | None:
    """Validate options once, before converting anything. Returns a message or None."""
    if not provided:
        return None
    reg = registry.get_registry()
    used: set[str] = set()
    known_conversions = 0
    for source in {format_from_path(job.src) for job in jobs if not job.error}:
        if source is None or not reg.can_convert(source, target):
            continue
        known_conversions += 1
        specs = reg.get(source, target).options
        chosen = {k: v for k, v in provided.items() if k in {s.name for s in specs}}
        try:
            validate_options(specs, chosen)
        except InvalidOptionError as exc:
            return str(exc)
        used |= chosen.keys()
    unused = sorted(set(provided) - used)
    if known_conversions and unused:
        names = ", ".join(f"'{name}'" for name in unused)
        return f"Option {names} does not apply to the files being converted."
    return None


def run_job(job: Job, target: str, provided: Mapping[str, Any], overwrite: bool = False) -> Path:
    """Run one planned job. Raises ``ConverterError`` (or the planning error)."""
    if job.error:
        raise job.error
    options = options_for_job(job.src, target, provided)
    return convert(job.src, job.dst, options=options, overwrite=overwrite)
