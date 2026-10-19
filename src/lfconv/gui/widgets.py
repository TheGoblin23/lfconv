import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable

from ..core.options import Option, choice_label, choice_value
from . import messages


class OptionsPanel(ttk.Frame):
    """Controls for the options of the chosen conversion, built from their declarations."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._specs: list[Option] = []
        self._vars: dict[str, tk.Variable] = {}

    @property
    def has_options(self) -> bool:
        return bool(self._specs)

    def set_options(self, specs: Iterable[Option]) -> None:
        """Rebuild the controls, keeping what was typed for options that remain."""
        remembered = {name: var.get() for name, var in self._vars.items()}
        for child in self.winfo_children():
            child.destroy()
        self._specs = list(specs)
        self._vars = {}
        for row, spec in enumerate(self._specs):
            self._add_row(row, spec, remembered.get(spec.name))

    def values(self) -> dict[str, Any]:
        """Current values; text that is not valid is passed on as is for validation to report."""
        return {spec.name: _parse(spec, self._vars[spec.name].get()) for spec in self._specs}

    def set_enabled(self, enabled: bool) -> None:
        for child in self.winfo_children():
            child.state(["!disabled" if enabled else "disabled"])

    def _add_row(self, row: int, spec: Option, remembered: Any) -> None:
        label = messages.option_name(spec.name)
        if spec.kind == "bool":
            var: tk.Variable = tk.BooleanVar(value=bool(spec.default if remembered is None else remembered))
            ttk.Checkbutton(self, text=label, variable=var).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=2)
        else:
            var = tk.StringVar(value=_initial_text(spec, remembered))
            ttk.Label(self, text=f"{label}:").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            _make_control(self, spec, var).grid(row=row, column=1, sticky="w")
        ttk.Label(self, text=spec.help, foreground="gray40").grid(row=row, column=2, sticky="w", padx=(10, 0))
        self._vars[spec.name] = var


def _initial_text(spec: Option, remembered: Any) -> str:
    if remembered is not None and (not spec.choices or remembered in map(choice_label, spec.choices)):
        return str(remembered)
    return choice_label(spec.default) if spec.choices else str(spec.default)


def _make_control(master: tk.Misc, spec: Option, var: tk.Variable) -> ttk.Widget:
    if spec.choices:
        return ttk.Combobox(master, textvariable=var, state="readonly", width=10,
                            values=[choice_label(choice) for choice in spec.choices])
    if spec.kind in ("int", "float") and spec.min is not None and spec.max is not None:
        return ttk.Spinbox(master, textvariable=var, from_=spec.min, to=spec.max, width=8,
                           increment=1 if spec.kind == "int" else 0.1)
    return ttk.Entry(master, textvariable=var, width=12)


def _parse(spec: Option, raw: Any) -> Any:
    if spec.kind == "bool":
        return bool(raw)
    if spec.kind in ("int", "float"):
        try:
            return (int if spec.kind == "int" else float)(str(raw).strip())
        except ValueError:
            return raw
    return choice_value(spec, raw)
