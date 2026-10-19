"""Runs a batch on a background thread and reports through a queue. No Tk here.

The window never calls the converters: it starts a worker and polls ``poll()``.
"""

import queue
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..core.batch import Job, run_job
from ..core.errors import ConverterError


@dataclass(frozen=True)
class Started:
    index: int
    total: int
    job: Job


@dataclass(frozen=True)
class Converted:
    index: int
    total: int
    job: Job


@dataclass(frozen=True)
class Failed:
    index: int
    total: int
    job: Job
    error: Exception


@dataclass(frozen=True)
class Finished:
    converted: int
    failed: int
    stopped: bool  # some jobs were never started


Event = Started | Converted | Failed | Finished


class BatchWorker:
    """Converts jobs one after another; ``Finished`` is always the last event."""

    def __init__(
        self,
        jobs: Iterable[Job],
        target: str,
        options: Mapping[str, Any],
        overwrite: bool = False,
    ) -> None:
        self._jobs = list(jobs)
        self._target = target
        self._options = dict(options)
        self._overwrite = overwrite
        self._events: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lfconv-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Do not start new files; the one being converted is finished."""
        self._stop.set()

    def poll(self) -> list[Event]:
        """Events produced since the last call. Never blocks."""
        events: list[Event] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def _run(self) -> None:
        total = len(self._jobs)
        converted = failed = 0
        try:
            for index, job in enumerate(self._jobs, start=1):
                if self._stop.is_set():
                    break
                self._events.put(Started(index, total, job))
                try:
                    run_job(job, self._target, self._options, self._overwrite)
                except Exception as exc:  # one bad file must not stop the batch
                    if not isinstance(exc, ConverterError):
                        traceback.print_exception(exc)
                    failed += 1
                    self._events.put(Failed(index, total, job, exc))
                else:
                    converted += 1
                    self._events.put(Converted(index, total, job))
        finally:
            self._events.put(Finished(converted, failed, converted + failed < total))
