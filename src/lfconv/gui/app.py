import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..converters import load_builtin_converters
from ..core.api import describe_converters
from ..core.formats import extensions
from . import messages
from .model import PlanError, Selection
from .widgets import OptionsPanel
from .worker import BatchWorker, Converted, Failed, Finished, Started

_POLL_MS = 100
_MAX_LISTED_FAILURES = 5
_ERROR_COLOR = "#b00020"


class App(ttk.Frame):
    """The window. It only shows state: conversions run in a ``BatchWorker`` thread."""

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, padding=12)
        self._window = root
        self._selection = Selection()
        self._targets: list[str] = []
        self._out_dir: Path | None = None
        self._worker: BatchWorker | None = None
        self._closing = False
        self._status: dict[Path, str] = {}
        self._failed: set[Path] = set()
        self._failures: list[tuple[str, str]] = []
        self._rows: dict[Path, str] = {}
        self._paths: dict[str, Path] = {}
        self._total = self._done = 0
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.pack(fill="both", expand=True)
        self._refresh_targets()

    # --- public API (used by the dialogs below and by tests) -------------------

    @property
    def busy(self) -> bool:
        return self._worker is not None

    @property
    def message(self) -> str:
        return self._message.get()

    def add_paths(self, paths) -> None:
        summary = self._selection.add(paths)
        self._refresh_targets()
        self._message.set(messages.added(summary.added, summary.unsupported, summary.duplicates))

    def set_target(self, fmt: str) -> None:
        if fmt in self._targets:
            self._target_box.current(self._targets.index(fmt))
            self._target_changed()

    def set_output_dir(self, path: Path | None) -> None:
        self._out_dir = path
        self._out_label.configure(text=_shorten(path) if path else messages.SAME_FOLDER)

    def start(self) -> None:
        if self.busy:
            return
        target = self._current_target()
        if not self._selection.entries or target is None:
            return
        provided = self._options_panel.values()
        try:
            plan = self._selection.plan(target, self._out_dir, provided)
        except PlanError as exc:
            messagebox.showerror(messages.ERROR_TITLE, str(exc), parent=self)
            return

        self._status, self._failed, self._failures = {}, set(), []
        for entry in plan.skipped:
            self._status[entry.path] = messages.STATUS_UNAVAILABLE.format(target=messages.format_name(target))
        self._render_rows()
        self._total, self._done = len(plan.jobs), 0
        if self._total == 1:
            self._progress.configure(mode="indeterminate")
            self._progress.start(12)
        else:
            self._progress.configure(mode="determinate", maximum=self._total, value=0)
        self._message.set(messages.progress(0, self._total))
        self._worker = BatchWorker(plan.jobs, target, provided, self._overwrite_var.get())
        self._set_busy(True)
        self._worker.start()
        self.after(_POLL_MS, self._poll)

    # --- layout ------------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, minsize=46)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._add_files_button = ttk.Button(toolbar, text=messages.ADD_FILES, command=self._ask_files)
        self._add_folder_button = ttk.Button(toolbar, text=messages.ADD_FOLDER, command=self._ask_folder)
        self._remove_button = ttk.Button(toolbar, text=messages.REMOVE, command=self._remove_selected)
        self._clear_button = ttk.Button(toolbar, text=messages.CLEAR, command=self._clear)
        for button in (self._add_files_button, self._add_folder_button, self._remove_button, self._clear_button):
            button.pack(side="left", padx=(0, 6))

        table = ttk.Frame(self)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self._tree = ttk.Treeview(table, columns=("file", "type", "status"), show="headings",
                                  selectmode="extended", height=8)
        for column, title, width, stretch in (
            ("file", messages.COLUMN_FILE, 230, True),
            ("type", messages.COLUMN_TYPE, 70, False),
            ("status", messages.COLUMN_STATUS, 250, True),
        ):
            self._tree.heading(column, text=title, anchor="w")
            self._tree.column(column, width=width, stretch=stretch, anchor="w")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._row_selected)
        self._tree.bind("<Delete>", lambda _event: self._remove_selected())

        self._detail = ttk.Label(self, text="", wraplength=580, justify="left", foreground=_ERROR_COLOR)
        self._detail.grid(row=2, column=0, sticky="nw", pady=(6, 0))

        settings = ttk.Frame(self)
        settings.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        settings.columnconfigure(3, weight=1)
        ttk.Label(settings, text=messages.CONVERT_TO).grid(row=0, column=0, sticky="w")
        self._target_box = ttk.Combobox(settings, state="readonly", width=10)
        self._target_box.grid(row=0, column=1, padx=(6, 18))
        self._target_box.bind("<<ComboboxSelected>>", lambda _event: self._target_changed())
        ttk.Label(settings, text=messages.SAVE_IN).grid(row=0, column=2, sticky="w")
        self._out_label = ttk.Label(settings, text=messages.SAME_FOLDER, anchor="w")
        self._out_label.grid(row=0, column=3, sticky="ew", padx=6)
        self._choose_button = ttk.Button(settings, text=messages.CHOOSE, command=self._ask_output)
        self._reset_button = ttk.Button(settings, text=messages.RESET, command=lambda: self.set_output_dir(None))
        self._choose_button.grid(row=0, column=4, padx=(0, 6))
        self._reset_button.grid(row=0, column=5)
        self._options_panel = OptionsPanel(settings)
        self._options_panel.grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self._overwrite_var = tk.BooleanVar(value=False)
        self._overwrite_check = ttk.Checkbutton(settings, text=messages.OVERWRITE, variable=self._overwrite_var)
        self._overwrite_check.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))

        self._progress = ttk.Progressbar(self, mode="determinate")
        self._progress.grid(row=4, column=0, sticky="ew", pady=(12, 4))
        footer = ttk.Frame(self)
        footer.grid(row=5, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._message = tk.StringVar(value=messages.HINT_EMPTY)
        ttk.Label(footer, textvariable=self._message).grid(row=0, column=0, sticky="w")
        self._convert_button = ttk.Button(footer, text=messages.CONVERT, command=self.start)
        self._convert_button.grid(row=0, column=1)

        self._locked = [self._add_files_button, self._add_folder_button, self._remove_button,
                        self._clear_button, self._target_box, self._choose_button,
                        self._reset_button, self._overwrite_check]

    # --- list and targets ---------------------------------------------------------

    def _refresh_targets(self) -> None:
        previous = self._current_target()
        self._targets = self._selection.available_targets()
        self._target_box["values"] = [messages.format_name(t) for t in self._targets]
        chosen = previous if previous in self._targets else self._selection.default_target()
        if chosen is None:
            self._target_box.set("")
        else:
            self._target_box.current(self._targets.index(chosen))
        self._target_changed()

    def _target_changed(self) -> None:
        target = self._current_target()
        self._status, self._failed = {}, set()
        if target is not None:
            ready = {entry.path for entry in self._selection.convertible(target)}
            for entry in self._selection.entries:
                if entry.path not in ready:
                    self._status[entry.path] = messages.STATUS_UNAVAILABLE.format(
                        target=messages.format_name(target))
        self._options_panel.set_options(self._selection.options_for(target) if target else [])
        self._render_rows()
        count = len(self._selection.convertible(target)) if target else 0
        self._message.set(messages.ready(count) if self._selection.entries else messages.HINT_EMPTY)
        self._update_buttons()

    def _current_target(self) -> str | None:
        index = self._target_box.current()
        return self._targets[index] if 0 <= index < len(self._targets) else None

    def _render_rows(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._rows, self._paths = {}, {}
        for entry in self._selection.entries:
            row = self._tree.insert("", "end", values=(
                entry.path.name, messages.format_name(entry.format), self._status.get(entry.path, "")))
            self._rows[entry.path] = row
            self._paths[row] = entry.path
        self._detail.configure(text="")

    def _set_row_status(self, path: Path, text: str, failed: bool = False) -> None:
        self._status[path] = text
        if failed:
            self._failed.add(path)
        if path in self._rows:
            self._tree.set(self._rows[path], "status", text)

    def _row_selected(self, _event: object = None) -> None:
        selected = self._tree.selection()
        path = self._paths.get(selected[0]) if len(selected) == 1 else None
        if path in self._failed:
            self._detail.configure(text=f"{messages.FAILED_TITLE}\n{self._status[path]}")
        else:
            self._detail.configure(text="")

    def _remove_selected(self) -> None:
        if self.busy:
            return
        self._selection.remove(self._tree.index(row) for row in self._tree.selection())
        self._refresh_targets()

    def _clear(self) -> None:
        if self.busy:
            return
        self._selection.clear()
        self._refresh_targets()

    # --- dialogs ---------------------------------------------------------------------

    def _ask_files(self) -> None:
        names = filedialog.askopenfilenames(parent=self, title=messages.PICK_FILES, filetypes=_file_types())
        if isinstance(names, str):
            names = self.tk.splitlist(names)
        if names:
            self.add_paths(names)

    def _ask_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title=messages.PICK_FOLDER)
        if folder:
            self.add_paths([folder])

    def _ask_output(self) -> None:
        folder = filedialog.askdirectory(parent=self, title=messages.PICK_OUTPUT, mustexist=False)
        if folder:
            self.set_output_dir(Path(folder))

    # --- running -----------------------------------------------------------------------

    def _poll(self) -> None:
        assert self._worker is not None
        finished: Finished | None = None
        for event in self._worker.poll():
            if isinstance(event, Started):
                self._set_row_status(event.job.src, messages.STATUS_CONVERTING)
            elif isinstance(event, Converted):
                self._set_row_status(event.job.src, messages.STATUS_DONE.format(name=event.job.dst.name))
                self._advance()
            elif isinstance(event, Failed):
                reason = messages.failure_reason(event.error)
                self._failures.append((event.job.src.name, reason))
                self._set_row_status(event.job.src, reason, failed=True)
                self._advance()
            elif isinstance(event, Finished):
                finished = event
        if finished is None:
            self.after(_POLL_MS, self._poll)
        else:
            self._finish(finished)

    def _advance(self) -> None:
        self._done += 1
        if self._total > 1:
            self._progress.configure(value=self._done)
            self._message.set(messages.progress(self._done, self._total))

    def _finish(self, event: Finished) -> None:
        self._worker = None
        self._progress.stop()
        self._progress.configure(mode="determinate", maximum=max(self._total, 1), value=self._done)
        self._set_busy(False)
        self._message.set(messages.finished(event.converted, event.failed, event.stopped, self._total))
        if self._closing:
            self._window.destroy()
        elif self._failures:
            listed = [f"{name}: {reason}" for name, reason in self._failures[:_MAX_LISTED_FAILURES]]
            if len(self._failures) > _MAX_LISTED_FAILURES:
                listed.append(f"…and {len(self._failures) - _MAX_LISTED_FAILURES} more.")
            messagebox.showwarning(messages.SOME_FAILED_TITLE,
                                   "\n".join(listed) + f"\n\n{messages.SOME_FAILED_HINT}", parent=self)

    def _set_busy(self, busy: bool) -> None:
        for widget in self._locked:
            widget.state(["disabled" if busy else "!disabled"])
        self._options_panel.set_enabled(not busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        ready = bool(self._selection.entries) and self._current_target() is not None and not self.busy
        self._convert_button.state(["!disabled" if ready else "disabled"])
        if self._options_panel.has_options:
            self._options_panel.grid()
        else:
            self._options_panel.grid_remove()

    def _on_close(self) -> None:
        if self._worker is None:
            self._window.destroy()
        elif messagebox.askyesno(messages.CLOSE_BUSY_TITLE, messages.CLOSE_BUSY, parent=self):
            self._closing = True
            self._worker.stop()
            self._message.set(messages.STOPPING)


def _file_types() -> list[tuple[str, str]]:
    patterns: list[str] = []
    for source in sorted({c["source"] for c in describe_converters()}):
        for extension in extensions(source):
            patterns += [f"*.{extension}", f"*.{extension.upper()}"]
    return [(messages.SUPPORTED_FILES, " ".join(patterns)), (messages.ALL_FILES, "*.*")]


def _shorten(path: Path, limit: int = 46) -> str:
    text = str(path)
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


def _enable_hidpi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def run() -> int:
    load_builtin_converters()
    _enable_hidpi()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Could not open a window: {exc}", file=sys.stderr)
        return 1
    root.title(messages.TITLE)
    root.minsize(640, 480)
    App(root)
    root.mainloop()
    return 0
