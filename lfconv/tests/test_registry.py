import json

import pytest

from lfconv import (
    Option,
    UnsupportedFormatError,
    can_convert,
    describe_converters,
    get_available_conversions,
    register_converter,
)
from lfconv.core import registry as registry_module
from lfconv.core.errors import ConverterError


def noop(src, dst, options):
    pass


def test_register_and_query():
    register_converter("png", "webp", noop)
    assert can_convert("png", "webp")
    assert not can_convert("webp", "png")


def test_formats_are_normalized():
    register_converter("jpeg", "PNG", noop)
    assert can_convert("jpg", "png")
    assert can_convert(".JPEG", "png")


def test_unknown_or_empty_formats_do_not_raise_in_queries():
    assert not can_convert("nope", "nada")
    assert not can_convert("", "")
    assert get_available_conversions("") == []


def test_available_conversions_are_sorted():
    register_converter("png", "webp", noop)
    register_converter("png", "jpg", noop)
    register_converter("csv", "json", noop)
    assert get_available_conversions("png") == ["jpg", "webp"]
    assert get_available_conversions("PNG") == ["jpg", "webp"]
    assert get_available_conversions("bmp") == []


def test_duplicate_registration_fails_unless_replaced():
    register_converter("png", "webp", noop)
    with pytest.raises(ValueError):
        register_converter("png", "webp", noop)
    register_converter("png", "webp", noop, replace=True)


def test_get_unknown_conversion_raises():
    with pytest.raises(UnsupportedFormatError, match="PNG to XYZ"):
        registry_module.get_registry().get("png", "xyz")


def test_describe_is_plain_json_serializable_data():
    register_converter(
        "png", "webp", noop,
        options=(Option("quality", "int", 85, "Output quality", min=1, max=100),),
    )
    register_converter("csv", "json", noop)
    described = describe_converters()
    json.dumps(described)
    assert [(d["source"], d["target"]) for d in described] == [("csv", "json"), ("png", "webp")]
    assert described[1]["options"][0]["name"] == "quality"
    assert described[1]["options"][0]["max"] == 100


def test_error_hierarchy_and_codes():
    from lfconv.core import errors

    classes = [
        errors.UnsupportedFormatError, errors.InvalidFileError, errors.InvalidOptionError,
        errors.ConversionError, errors.OutputError,
    ]
    assert all(issubclass(c, ConverterError) for c in classes)
    codes = [c.code for c in classes]
    assert len(set(codes)) == len(codes)
