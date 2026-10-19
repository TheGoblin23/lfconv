import pytest

from lfconv import UnsupportedFormatError
from lfconv.core.formats import format_from_path, normalize_format


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("JPEG", "jpg"), (".PNG", "png"), ("tif", "tiff"), (" webp ", "webp"), ("jpg", "jpg")],
)
def test_normalize_format(raw, expected):
    assert normalize_format(raw) == expected


@pytest.mark.parametrize("raw", ["", " ", "."])
def test_normalize_rejects_empty(raw):
    with pytest.raises(UnsupportedFormatError):
        normalize_format(raw)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/b/photo.JPEG", "jpg"),
        ("scan.TIF", "tiff"),
        ("archive.tar.gz", "gz"),
        ("noextension", None),
        ("trailingdot.", None),
    ],
)
def test_format_from_path(path, expected):
    assert format_from_path(path) == expected
