"""The list of files the user picked and what can be done with it. No Tk here."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..core.api import PathLike, can_convert, get_available_conversions
from ..core.batch import Job, check_options, options_for_target, plan_jobs
from ..core.formats import format_from_path
from ..core.options import Option
from . import messages


@dataclass(frozen=True)
class Entry:
    path: Path
    format: str


@dataclass(frozen=True)
class AddSummary:
    added: int = 0
    unsupported: int = 0
    duplicates: int = 0


@dataclass(frozen=True)
class Plan:
    jobs: list[Job]
    skipped: list[Entry]  # in the list, but cannot be converted to the chosen format


class PlanError(Exception):
    """The conversion cannot start; ``str(error)`` is written for the user."""


class Selection:
    def __init__(self) -> None:
        self.entries: list[Entry] = []
        self._keys: set[str] = set()

    def add(self, paths: Iterable[PathLike]) -> AddSummary:
        """Add files, or the files inside folders (not recursive, no hidden files)."""
        added = unsupported = duplicates = 0
        for raw in paths:
            for file in _expand(Path(raw)):
                fmt = format_from_path(file)
                key = _key(file)
                if not fmt or not get_available_conversions(fmt):
                    unsupported += 1
                elif key in self._keys:
                    duplicates += 1
                else:
                    self._keys.add(key)
                    self.entries.append(Entry(file, fmt))
                    added += 1
        return AddSummary(added, unsupported, duplicates)

    def remove(self, indices: Iterable[int]) -> None:
        drop = set(indices)
        self.entries = [entry for i, entry in enumerate(self.entries) if i not in drop]
        self._keys = {_key(entry.path) for entry in self.entries}

    def clear(self) -> None:
        self.entries = []
        self._keys = set()

    def available_targets(self) -> list[str]:
        """Every format at least one file can be converted to."""
        return sorted({t for entry in self.entries for t in get_available_conversions(entry.format)})

    def default_target(self) -> str | None:
        """A format every file can reach if there is one, else the first available."""
        if not self.entries:
            return None
        common = set.intersection(*(set(get_available_conversions(e.format)) for e in self.entries))
        pool = sorted(common) or self.available_targets()
        return pool[0] if pool else None

    def convertible(self, target: str) -> list[Entry]:
        return [entry for entry in self.entries if can_convert(entry.format, target)]

    def options_for(self, target: str) -> list[Option]:
        return options_for_target(target, {entry.format for entry in self.convertible(target)})

    def plan(self, target: str, out_dir: Path | None, provided: Mapping[str, Any]) -> Plan:
        ready = self.convertible(target)
        if not ready:
            raise PlanError(messages.NOTHING_TO_CONVERT.format(target=messages.format_name(target)))
        jobs, _ = plan_jobs([entry.path for entry in ready], target, out_dir)
        problem = check_options(jobs, target, provided)
        if problem:
            raise PlanError(problem)
        ready_paths = {entry.path for entry in ready}
        return Plan(jobs, [entry for entry in self.entries if entry.path not in ready_paths])


def _expand(path: Path) -> list[Path]:
    if path.is_dir():
        try:
            children = sorted(path.iterdir())
        except OSError:
            return []
        return [c for c in children if not c.name.startswith(".") and c.is_file()]
    return [path] if path.is_file() else []


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))
