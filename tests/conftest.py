import pytest

from lfconv.core import registry as registry_module
from lfconv.core.options import Option
from lfconv.core.registry import Registry


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch):
    """Every test gets an empty registry; none can touch the real one."""
    reg = Registry()
    monkeypatch.setattr(registry_module, "_default", reg)
    return reg


def _upper(src, dst, options):
    text = src.read_text(encoding="utf-8").upper()
    dst.write_text(text * options["repeat"], encoding="utf-8")


@pytest.fixture
def upper_converter(fresh_registry):
    """A tiny txt -> up converter used to exercise the core."""
    fresh_registry.register(
        "txt", "up", _upper, options=(Option("repeat", "int", 1, min=1, max=5),)
    )


@pytest.fixture
def src(tmp_path):
    path = tmp_path / "in.txt"
    path.write_text("hello", encoding="utf-8")
    return path
