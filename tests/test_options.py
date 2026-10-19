import pytest

from lfconv import InvalidOptionError, Option
from lfconv.core.options import validate_options


def quality(**overrides):
    base = {"name": "quality", "kind": "int", "default": 85, "min": 1, "max": 100}
    return Option(**{**base, **overrides})


def test_defaults_are_applied():
    assert validate_options([quality()], None) == {"quality": 85}


def test_valid_value_overrides_default():
    assert validate_options([quality()], {"quality": 50}) == {"quality": 50}


@pytest.mark.parametrize("value", [0, 101, "85", 85.5, True, None])
def test_invalid_int_values_are_rejected(value):
    with pytest.raises(InvalidOptionError):
        validate_options([quality()], {"quality": value})


def test_unknown_option_is_rejected():
    with pytest.raises(InvalidOptionError, match="unknown_thing"):
        validate_options([quality()], {"unknown_thing": 1})


def test_float_accepts_int_but_not_nan_or_bool():
    spec = Option("scale", "float", 1.0, min=0.1)
    assert validate_options([spec], {"scale": 2}) == {"scale": 2}
    for bad in (float("nan"), float("inf"), True, 0.01):
        with pytest.raises(InvalidOptionError):
            validate_options([spec], {"scale": bad})


def test_bool_is_strict():
    spec = Option("lossless", "bool", False)
    assert validate_options([spec], {"lossless": True}) == {"lossless": True}
    with pytest.raises(InvalidOptionError):
        validate_options([spec], {"lossless": 1})


def test_choices():
    spec = Option("mode", "str", "fast", choices=("fast", "small"))
    assert validate_options([spec], {"mode": "small"}) == {"mode": "small"}
    with pytest.raises(InvalidOptionError, match="fast, small"):
        validate_options([spec], {"mode": "other"})


def test_invalid_default_is_a_programmer_error():
    with pytest.raises(ValueError):
        Option("quality", "int", 0, min=1)
    with pytest.raises(ValueError):
        Option("x", "complex", 1)
