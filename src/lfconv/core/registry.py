from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import UnsupportedFormatError
from .formats import normalize_format
from .options import Option

# A converter reads ``source``, writes ``destination`` and returns nothing.
# It receives validated options with defaults applied. It must not infer the
# output format from ``destination``'s name: it is a temporary file.
ConvertFunc = Callable[[Path, Path, dict[str, Any]], None]


@dataclass(frozen=True)
class ConverterInfo:
    source: str
    target: str
    func: ConvertFunc
    options: tuple[Option, ...] = ()


class Registry:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ConverterInfo] = {}

    def register(
        self,
        source: str,
        target: str,
        func: ConvertFunc,
        options: tuple[Option, ...] = (),
        *,
        replace: bool = False,
    ) -> None:
        key = (normalize_format(source), normalize_format(target))
        if key in self._items and not replace:
            raise ValueError(f"A converter for {key[0]} -> {key[1]} is already registered.")
        self._items[key] = ConverterInfo(key[0], key[1], func, tuple(options))

    def get(self, source: str, target: str) -> ConverterInfo:
        try:
            return self._items[(normalize_format(source), normalize_format(target))]
        except (KeyError, UnsupportedFormatError):
            raise UnsupportedFormatError(
                f"Converting from {source.upper()} to {target.upper()} is not supported."
            ) from None

    def can_convert(self, source: str, target: str) -> bool:
        try:
            self.get(source, target)
        except UnsupportedFormatError:
            return False
        return True

    def targets(self, source: str) -> list[str]:
        try:
            source = normalize_format(source)
        except UnsupportedFormatError:
            return []
        return sorted(t for s, t in self._items if s == source)

    def infos(self) -> list[ConverterInfo]:
        """Every registered conversion, sorted by (source, target)."""
        return [info for _, info in sorted(self._items.items())]

    def describe(self) -> list[dict[str, Any]]:
        """Registered conversions as plain data (JSON-serializable)."""
        return [
            {
                "source": info.source,
                "target": info.target,
                "options": [asdict(option) for option in info.options],
            }
            for info in self.infos()
        ]


_default = Registry()


def get_registry() -> Registry:
    return _default


def register_converter(
    source: str,
    target: str,
    func: ConvertFunc,
    options: tuple[Option, ...] = (),
    *,
    replace: bool = False,
) -> None:
    get_registry().register(source, target, func, options, replace=replace)
