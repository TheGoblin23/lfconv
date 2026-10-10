import math
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from .errors import InvalidOptionError

Kind = Literal["int", "float", "bool", "str"]
_KINDS = ("int", "float", "bool", "str")


@dataclass(frozen=True)
class Option:
    """Declares one option a converter accepts.

    Only plain data, so front ends can build their controls from it and a
    future non-Python engine can publish the same description.
    """

    name: str
    kind: Kind
    default: Any
    help: str = ""
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"Unknown option kind: {self.kind!r}")
        problem = self.problem(self.default)
        if problem:
            raise ValueError(f"Invalid default for option '{self.name}': {problem}")

    def problem(self, value: Any) -> str | None:
        """Describe why ``value`` is not acceptable, or return None."""
        is_bool = isinstance(value, bool)
        if self.kind == "bool":
            if not is_bool:
                return "must be true or false"
        elif self.kind == "str":
            if not isinstance(value, str):
                return "must be text"
        else:
            accepted = int if self.kind == "int" else (int, float)
            if is_bool or not isinstance(value, accepted):
                return "must be a whole number" if self.kind == "int" else "must be a number"
            if isinstance(value, float) and not math.isfinite(value):
                return "must be a finite number"
            if self.min is not None and value < self.min:
                return f"must be at least {self.min}"
            if self.max is not None and value > self.max:
                return f"must be at most {self.max}"
        if self.choices is not None and value not in self.choices:
            return "must be one of: " + ", ".join(map(str, self.choices))
        return None


def validate_options(
    specs: Iterable[Option], options: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Apply defaults and reject unknown or invalid values."""
    supplied = dict(options or {})
    resolved: dict[str, Any] = {}
    for spec in specs:
        value = supplied.pop(spec.name, spec.default)
        problem = spec.problem(value)
        if problem:
            raise InvalidOptionError(f"Option '{spec.name}' {problem}.")
        resolved[spec.name] = value
    if supplied:
        raise InvalidOptionError(f"Unknown option: {', '.join(sorted(supplied))}.")
    return resolved
