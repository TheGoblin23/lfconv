# Architecture

This document explains how Local File Converter is built, how to extend it, and how its engine could later be replaced by a Rust implementation.

## Principles

- **Local only.** No network, no accounts, no telemetry. Enforced by tests.
- **Small and simple.** Standard library first; a new dependency needs a reason.
- **The engine is independent of the interfaces.** The CLI and the GUI contain no conversion logic.
- **Data in, data out.** The boundary of the engine is file paths, plain options and plain results.
- **Measure before optimising.** Nothing is rewritten for speed without numbers.

## Layers and the dependency rule

```text
        cli/                gui/
          \                  /
           \                /
            +---- core ----+        <- public API: convert(), can_convert(), ...
                    ^
                    |
              converters/           <- register themselves into core
```

- `core` depends on nothing else in the project and does not know Pillow, Tkinter or any format.
- `converters` depend on `core` only.
- `cli` and `gui` depend on `core` (plus `converters.load_builtin_converters()` to fill the registry at start-up).
- `gui/model.py` and `gui/worker.py` do not import Tkinter, so the logic of the window is tested without a display. Only `gui/app.py` and `gui/widgets.py` touch Tk.

```text
src/lfconv/
├── __init__.py           public API re-exports
├── __main__.py           python -m lfconv
├── core/
│   ├── api.py            convert(), can_convert(), get_available_conversions(), describe_converters()
│   ├── batch.py          planning and running many conversions (shared by CLI and GUI)
│   ├── errors.py         error hierarchy
│   ├── formats.py        format names, aliases, detection by extension
│   ├── options.py        Option declarations and validation
│   └── registry.py       the registry of converters
├── converters/
│   ├── __init__.py       load_builtin_converters()
│   ├── data.py           CSV <-> JSON, JSON -> TXT
│   ├── image.py          PNG/JPG/WebP and image -> PDF (Pillow)
│   ├── text.py           TXT -> PDF
│   └── pdf_writer.py     minimal streaming PDF writer used by text.py
├── cli/main.py           argparse front end, JSON events, exit codes
└── gui/                  model.py, worker.py, messages.py, widgets.py, app.py
```

## Core concepts

### Formats

Formats are lowercase names without a dot. Aliases are normalised (`jpeg` becomes `jpg`, `tif` becomes `tiff`). `core` detects the format from the file extension only. Checking that the *content* matches is each converter's job (the image converter, for instance, rejects a JPEG named `.png`).

### The registry

```python
register_converter("png", "webp", png_to_webp, options=(...))
can_convert("png", "webp")           # True
get_available_conversions("png")     # ["jpg", "pdf", "webp"]
describe_converters()                # plain data, JSON-serialisable
```

The registry is queryable **as data**. A front end that asks "what can be converted?" must work the same whether the answer comes from Python code or from another engine.

Registration is explicit: `load_builtin_converters()` registers everything visibly instead of relying on import side effects. Converters import heavy libraries (Pillow) inside their functions, so starting the CLI or reading `--help` does not load them. Image converters are only registered if Pillow is installed.

### The converter contract

```python
def my_converter(src: Path, dst: Path, options: dict) -> None: ...
```

- Read `src`, write `dst`, return nothing.
- `options` has been validated and has defaults applied.
- **Do not infer the output format from `dst`'s name.** It is a temporary file; pass the format explicitly to the writing library. The name does end with the target extension, but treat that as incidental.
- Raise `InvalidFileError` when the input is not valid. Raise other `ConverterError` subclasses for known situations. Any other exception is wrapped by the core into `ConversionError`, and an `OSError` is reported as `OutputError`.
- Stream when the format allows it, and do not keep whole files in memory needlessly.
- Never print, never touch the network, never keep state between calls.

### Options

An `Option` declares a name, a kind (`int`, `float`, `bool`, `str`), a default, help text and optional limits or choices. Declarations are plain data, so the CLI generates `--quality`-style flags and the GUI generates spin boxes and drop-downs from them. Unknown options and invalid values raise `InvalidOptionError`.

### Errors

| Class | `code` | Typical cause |
|---|---|---|
| `UnsupportedFormatError` | `unsupported_format` | No converter for this pair, or the format cannot be determined |
| `InvalidFileError` | `invalid_file` | Missing, empty, unreadable, corrupt or mislabelled input |
| `InvalidOptionError` | `invalid_option` | Unknown option or invalid value |
| `ConversionError` | `conversion_failed` | The converter failed unexpectedly |
| `OutputError` | `output_error` | Output exists, folder not writable, disk full, same file as input |

`str(error)` is a message written for people and contains only the file name, never the full path. The technical cause is in `error.__cause__` (shown by `--verbose`). `code` is stable and meant for translation and machine use.

### `convert()`

```python
convert(input_path, output_path, source_format=None, target_format=None,
        options=None, *, overwrite=False) -> Path
```

Formats default to the extensions. Output is written to a hidden temporary file in the same folder and renamed on success, so a failure never leaves a partial file and never damages an existing output. Missing output folders are created. Nothing is overwritten unless `overwrite=True`. Empty inputs are rejected.

### Batches

`core/batch.py` turns a list of inputs into `Job`s (`plan_jobs`), validates options once before anything runs (`check_options`), filters options per conversion (`options_for_job`) and runs one job (`run_job`). Planning problems (for example two inputs that would write the same file) become errors attached to the job instead of silent overwrites. The CLI and the GUI share all of it.

## Adding a converter

1. Write the function in the module for its kind of input (or a new module under `converters/`).
2. Register it in that module's `register()` function, using `replace=True` so that loading twice is harmless.
3. If it is a new module, call its `register()` from `load_builtin_converters()`.
4. Add tests: a valid conversion, a wrong or corrupt file, an empty file, options, and a failure that must leave no partial output. The existing tests for `data.py` are a good template.

A complete example that registers a converter at runtime (this runs as is):

```python
from pathlib import Path

from lfconv import InvalidFileError, Option, convert, register_converter


def txt_to_md(src: Path, dst: Path, options: dict) -> None:
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidFileError("The file is not valid UTF-8 text.") from exc
    dst.write_text(f"{'#' * options['level']} {text}", encoding="utf-8")


register_converter(
    "txt", "md", txt_to_md,
    options=(Option("level", "int", 1, "Heading level.", min=1, max=6),),
)

convert("note.txt", "out/note.md", options={"level": 2})
```

A converter registered like this exists only inside that Python process. Registered as a built-in (steps 2 and 3), the converter is also available in the `lfconv` command, where `--level` appears for `--to md`, and in the window, which shows a "Level" control, with no change to either front end.

## The window

- `Selection` (model) holds the list of files, computes the available targets and the options that apply, and builds the plan. It has no Tk dependency.
- `BatchWorker` runs the jobs on one background thread and reports `Started`, `Converted`, `Failed` and `Finished` events through a queue. `poll()` never blocks.
- `App` only displays state. It polls the worker every 100 ms with `after()`. **Only the main thread touches Tk**; the worker never does.
- Closing the window during a conversion asks for confirmation, finishes the current file and then closes.
- All user-visible text lives in `gui/messages.py`.

Tkinter widgets inherit from large classes, so an attribute named like a Tk method (for example `self._options`) silently breaks the widget. A test guards against it.

## Process contract (for a future engine)

The command line is a stable, language-neutral interface to the engine, and the GUI could drive any executable that speaks it.

**Exit codes:** `0` all converted, `1` some failed, `2` invalid usage or nothing to convert, `130` interrupted.

**Events with `--json`**, one JSON object per line on standard output (ASCII-escaped):

| `event` | Fields |
|---|---|
| `converted` | `index`, `total`, `input`, `output` |
| `failed` | `index`, `total`, `input`, `error: {code, message}` |
| `skipped` | `input`, `reason` |
| `summary` | `converted`, `failed`, `skipped`, `interrupted` |
| `error` | `error: {code: "usage", message}` (invalid usage) |

**Capabilities with `--list --json`:** an array with one entry per conversion.

```json
{
  "source": "png",
  "target": "jpg",
  "options": [
    {"name": "quality", "kind": "int", "default": 85,
     "help": "Output quality: higher looks better and is larger.",
     "min": 1, "max": 100, "choices": null}
  ]
}
```

## Migration to Rust

Not started. These are the rules for when it is.

1. **Measure first.** Build the benchmarks (v0.4) and find the real bottlenecks. Do not rewrite everything.
2. **Expect modest gains for images.** Pillow already uses native C libraries (libjpeg, libwebp), so a Rust image path may gain little in speed. The likelier wins are start-up time, installed size and not needing a Python runtime. Measure these too.
3. **Freeze the contract above** (API, `describe` data, error codes, exit codes, JSON events) and keep equivalent tests, so Python and Rust can be compared on the same inputs, outputs and failures.
4. **Two integration routes**, to decide with data:
   - *Engine as an executable* that speaks the process contract; the window drives it as a subprocess. Cleanest separation, one more process.
   - *Native extension* (for example PyO3) replacing individual converters inside the Python package. Less process overhead, more build complexity.
5. **Migrate the processing components first** (image, CSV, JSON, PDF writing). Keep in Python whatever does not benefit.
6. **Compare** results, speed and memory against the recorded Python baseline, then build cross-platform binaries.

Choosing Rust libraries (images, PDF, CSV, JSON, CLI, GUI) should consider maintenance activity, license compatibility, cross-platform support, performance and final binary size, not popularity alone. A PDF library with an incompatible license is the same trap as in the Python version, where the popular PyMuPDF is AGPL-licensed and was avoided on purpose.

## Decisions and known limits

- Text input is UTF-8 only; other encodings are rejected with a clear message rather than converted with broken characters.
- PDF from text uses the built-in Courier font and Windows-1252, to stay dependency-free. Full Unicode would need an embedded font or a PDF library; the converter sits behind the registry, so swapping it affects nothing else.
- JSON conversions load the whole file in memory. CSV to JSON and TXT to PDF stream.
- Format detection by extension is deliberate and simple; content checks belong to the converters.
- Conversions are sequential in v0.1. Parallel batches, cancellation and drag and drop are planned for v0.2.
