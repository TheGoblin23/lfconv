class ConverterError(Exception):
    """Base class for every error raised by the converter.

    ``str(error)`` is written for end users. The technical cause, when there
    is one, is available as ``error.__cause__``. ``code`` is a stable
    identifier that front ends can use for translation or ``--json`` output.
    """

    code = "converter_error"


class UnsupportedFormatError(ConverterError):
    code = "unsupported_format"


class InvalidFileError(ConverterError):
    code = "invalid_file"


class InvalidOptionError(ConverterError):
    code = "invalid_option"


class ConversionError(ConverterError):
    code = "conversion_failed"


class OutputError(ConverterError):
    code = "output_error"
