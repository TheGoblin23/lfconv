def load_builtin_converters() -> None:
    """Register every built-in converter. Safe to call more than once.

    Image converters are skipped when Pillow is not installed.
    """
    from . import data, image, text

    data.register()
    text.register()
    if image.is_available():
        image.register()
