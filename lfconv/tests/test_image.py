import random

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageCms  # noqa: E402

from lfconv import (  # noqa: E402
    ConversionError,
    InvalidFileError,
    InvalidOptionError,
    can_convert,
    convert,
    describe_converters,
    get_available_conversions,
)
from lfconv.converters import image as image_converters  # noqa: E402
from lfconv.converters import load_builtin_converters  # noqa: E402

NAMES = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}
PAIRS = [(s, t) for s in NAMES for t in NAMES if s != t]


@pytest.fixture(autouse=True)
def builtin():
    load_builtin_converters()


def save(tmp_path, name, img, **kwargs):
    path = tmp_path / name
    img.save(path, **kwargs)
    return path


def info(path):
    with Image.open(path) as img:
        return img.format, img.mode, img.size


def pixel(path, xy, mode="RGB"):
    with Image.open(path) as img:
        return img.convert(mode).getpixel(xy)


def noisy(size=(128, 128)):
    data = random.Random(0).randbytes(size[0] * size[1] * 3)
    return Image.frombytes("RGB", size, data)


def near(actual, expected, tolerance=12):
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


def srgb_profile():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


# --- registration -------------------------------------------------------------

def test_every_pair_and_pdf_is_registered():
    for source, target in PAIRS:
        assert can_convert(source, target)
    for source in NAMES:
        assert can_convert(source, "pdf")
    assert get_available_conversions("png") == ["jpg", "pdf", "webp"]
    assert not can_convert("png", "png")


def test_quality_is_declared_only_where_it_applies():
    options = {(d["source"], d["target"]): [o["name"] for o in d["options"]]
               for d in describe_converters()}
    assert options[("png", "jpg")] == ["quality"]
    assert options[("png", "webp")] == ["quality"]
    assert options[("jpg", "pdf")] == ["quality"]
    assert options[("jpg", "png")] == []


def test_image_converters_are_skipped_without_pillow(monkeypatch, fresh_registry):
    monkeypatch.setattr(image_converters, "is_available", lambda: False)
    fresh_registry._items.clear()
    load_builtin_converters()
    assert not can_convert("png", "webp")
    assert can_convert("csv", "json")


# --- basic conversions -----------------------------------------------------------

@pytest.mark.parametrize(("source", "target"), PAIRS)
def test_conversion_keeps_size_and_colour(tmp_path, source, target):
    src = save(tmp_path, f"in.{source}", Image.new("RGB", (32, 24), (200, 30, 30)),
               format=NAMES[source])
    out = tmp_path / f"out.{target}"
    convert(src, out)
    fmt, _, size = info(out)
    assert (fmt, size) == (NAMES[target], (32, 24))
    assert near(pixel(out, (5, 5)), (200, 30, 30))


@pytest.mark.parametrize("source", NAMES)
def test_image_to_pdf(tmp_path, source):
    src = save(tmp_path, f"in.{source}", Image.new("RGB", (32, 24), "teal"), format=NAMES[source])
    out = tmp_path / "out.pdf"
    convert(src, out)
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")


def test_rgba_image_to_pdf_works(tmp_path):
    src = save(tmp_path, "in.png", Image.new("RGBA", (16, 16), (255, 0, 0, 0)))
    convert(src, tmp_path / "out.pdf")
    assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF")


def test_grayscale_stays_grayscale(tmp_path):
    src = save(tmp_path, "in.jpg", Image.new("L", (16, 16), 90))
    convert(src, tmp_path / "out.png")
    assert info(tmp_path / "out.png")[1] == "L"


def test_cmyk_jpeg_becomes_rgb_png(tmp_path):
    src = save(tmp_path, "in.jpg", Image.new("CMYK", (16, 16), (0, 255, 255, 0)))
    convert(src, tmp_path / "out.png")
    assert info(tmp_path / "out.png")[1] == "RGB"


def test_16_bit_grayscale_is_scaled_not_clipped(tmp_path):
    src = save(tmp_path, "in.png", Image.new("I;16", (8, 8), 40000))
    convert(src, tmp_path / "out.jpg")
    assert abs(pixel(tmp_path / "out.jpg", (2, 2), "L") - 156) <= 2


# --- transparency ---------------------------------------------------------------------

def rgba_with_block():
    img = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
    img.paste((0, 0, 255, 255), (10, 10, 20, 20))
    return img


@pytest.mark.parametrize("target", ["jpg", "pdf"])
def test_transparency_is_flattened_onto_white(tmp_path, target):
    src = save(tmp_path, "in.png", rgba_with_block())
    out = tmp_path / f"out.{target}"
    convert(src, out)
    if target == "jpg":
        assert near(pixel(out, (2, 2)), (255, 255, 255), 6)
        assert near(pixel(out, (15, 15)), (0, 0, 255), 25)


def test_palette_and_gray_alpha_transparency_become_white(tmp_path):
    palette = Image.new("P", (10, 10), 0)
    palette.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    p_src = save(tmp_path, "p.png", palette, transparency=0)
    la_src = save(tmp_path, "la.png", Image.new("LA", (10, 10), (0, 0)))
    for src in (p_src, la_src):
        out = tmp_path / f"{src.stem}.jpg"
        convert(src, out)
        assert near(pixel(out, (3, 3)), (255, 255, 255), 6)


def test_transparency_is_kept_for_webp_and_png(tmp_path):
    src = save(tmp_path, "in.png", rgba_with_block())
    convert(src, tmp_path / "out.webp")
    assert pixel(tmp_path / "out.webp", (2, 2), "RGBA")[3] == 0
    assert pixel(tmp_path / "out.webp", (15, 15), "RGBA")[3] == 255
    webp_as_png = tmp_path / "back.png"
    convert(tmp_path / "out.webp", webp_as_png)
    assert pixel(webp_as_png, (2, 2), "RGBA")[3] == 0


# --- orientation, frames, metadata -----------------------------------------------

def test_exif_orientation_is_applied(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6
    src = save(tmp_path, "in.jpg", Image.new("RGB", (40, 20), "red"), exif=exif)
    convert(src, tmp_path / "out.png")
    assert info(tmp_path / "out.png")[2] == (20, 40)


def test_exif_metadata_is_dropped(tmp_path):
    exif = Image.Exif()
    exif[0x010F] = "Secret Camera Co"
    src = save(tmp_path, "in.jpg", Image.new("RGB", (16, 16), "red"), exif=exif)
    for target in ("out.webp", "out.png"):
        out = tmp_path / target
        convert(src, out)
        with Image.open(out) as img:
            assert len(img.getexif()) == 0
            assert b"Secret Camera" not in out.read_bytes()


def test_icc_profile_is_preserved(tmp_path):
    profile = srgb_profile()
    src = save(tmp_path, "in.png", Image.new("RGB", (16, 16), "red"), icc_profile=profile)
    for target in ("jpg", "webp"):
        out = tmp_path / f"out.{target}"
        convert(src, out)
        with Image.open(out) as img:
            assert img.info.get("icc_profile") == profile


def test_animated_webp_uses_first_frame_only(tmp_path):
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "green", "blue")]
    src = save(tmp_path, "in.webp", frames[0], save_all=True, append_images=frames[1:],
               duration=100, lossless=True)
    convert(src, tmp_path / "out.png")
    with Image.open(tmp_path / "out.png") as img:
        assert getattr(img, "n_frames", 1) == 1
        assert near(img.convert("RGB").getpixel((3, 3)), (255, 0, 0))


def test_multi_picture_jpeg_is_accepted(tmp_path):
    a, b = Image.new("RGB", (10, 10), "red"), Image.new("RGB", (10, 10), "blue")
    src = save(tmp_path, "phone.jpg", a, format="MPO", save_all=True, append_images=[b])
    convert(src, tmp_path / "out.png")
    assert info(tmp_path / "out.png")[2] == (10, 10)


# --- options ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", ["jpg", "webp", "pdf"])
def test_lower_quality_gives_smaller_files(tmp_path, target):
    src = save(tmp_path, "in.png", noisy())
    low, high = tmp_path / f"low.{target}", tmp_path / f"high.{target}"
    convert(src, low, options={"quality": 20})
    convert(src, high, options={"quality": 95})
    assert low.stat().st_size < high.stat().st_size


@pytest.mark.parametrize("quality", [0, 101, "high", 50.5])
def test_invalid_quality_is_rejected(tmp_path, quality):
    src = save(tmp_path, "in.png", Image.new("RGB", (8, 8)))
    with pytest.raises(InvalidOptionError):
        convert(src, tmp_path / "out.jpg", options={"quality": quality})


def test_quality_is_not_accepted_for_lossless_png_target(tmp_path):
    src = save(tmp_path, "in.jpg", Image.new("RGB", (8, 8)))
    with pytest.raises(InvalidOptionError):
        convert(src, tmp_path / "out.png", options={"quality": 80})


# --- invalid and corrupt inputs ------------------------------------------------------

def test_content_must_match_the_extension(tmp_path):
    png_as_jpg = save(tmp_path, "fake.jpg", Image.new("RGB", (8, 8)), format="PNG")
    with pytest.raises(InvalidFileError, match="JPG.*content is PNG"):
        convert(png_as_jpg, tmp_path / "a.webp")
    jpg_as_png = save(tmp_path, "fake.png", Image.new("RGB", (8, 8)), format="JPEG")
    with pytest.raises(InvalidFileError, match="PNG.*content is JPEG"):
        convert(jpg_as_png, tmp_path / "b.webp")


def test_not_an_image(tmp_path):
    src = tmp_path / "notes.png"
    src.write_bytes(b"this is plain text, not an image")
    with pytest.raises(InvalidFileError, match="not a valid image"):
        convert(src, tmp_path / "out.jpg")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.png"]


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_truncated_image(tmp_path, fmt):
    full = save(tmp_path, "full.tmp", noisy((96, 96)), format=fmt).read_bytes()
    src = tmp_path / ("cut.png" if fmt == "PNG" else "cut.jpg")
    src.write_bytes(full[: len(full) // 2])
    with pytest.raises(InvalidFileError, match="damaged or incomplete"):
        convert(src, tmp_path / "out.webp")
    assert not (tmp_path / "out.webp").exists()


def test_decompression_bomb_is_rejected(tmp_path, monkeypatch):
    src = save(tmp_path, "in.png", Image.new("RGB", (50, 50)))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(InvalidFileError, match="too large"):
        convert(src, tmp_path / "out.jpg")


def test_webp_dimension_limit_gives_a_clear_error(tmp_path):
    src = save(tmp_path, "wide.png", Image.new("RGB", (16384, 1)))
    with pytest.raises(ConversionError, match="too large for WebP"):
        convert(src, tmp_path / "out.webp")
    assert not (tmp_path / "out.webp").exists()


@pytest.mark.slow
def test_large_image(tmp_path):
    big = Image.linear_gradient("L").resize((6000, 4000)).convert("RGB")
    src = save(tmp_path, "big.png", big)
    for target in ("jpg", "webp"):
        convert(src, tmp_path / f"big.{target}")
        assert info(tmp_path / f"big.{target}")[2] == (6000, 4000)
