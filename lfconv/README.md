# Local File Converter

Convert files between formats **entirely on your computer**. Nothing is uploaded, no account is needed, and no network connection is used.

> **Status: alpha (v0.1.0 in development).** The package name `lfconv` is provisional.

It comes with a small desktop window and a command-line tool, both running on the same conversion engine.

## Why it exists

Most online converters ask you to upload your files to someone else's server. That is a poor deal for photos, spreadsheets with customer data or any document you would rather keep private, and it needs an internet connection and often an account.

Local File Converter does the work on your machine, keeps memory use low (large CSV and text files are processed as streams) and is small enough to read and audit.

## Features

- Convert PNG, JPG and WebP between each other, and images to PDF.
- Convert CSV to JSON, JSON to CSV, JSON to text, and text to PDF.
- Desktop window: pick files or a folder, choose the output format and folder, watch progress. The window never freezes while converting.
- Command-line tool for scripts and batches, with machine-readable `--json` output and fixed exit codes.
- Works with a whole folder at once.
- Never overwrites by default, and never leaves a half-written file behind.
- New formats are added by registering a small function (see [docs/architecture.md](docs/architecture.md)).

## Privacy

- **No network.** The code does not use sockets, HTTP or any online service. The test suite fails if a network module is imported (`tests/test_privacy.py`).
- **No account, no telemetry.** Nothing is collected: no file names, no paths, no personal information.
- **Your files stay where they are.** Results are written next to the originals, or in the folder you choose.
- **Metadata is dropped from images** (EXIF, including GPS location) when converting. The ICC colour profile is kept, because it changes how colours look. PDFs written by the tool contain no metadata (no dates, author or file names).
- **Temporary file.** While converting, a hidden file named like `.1a2b3c4d-photo.webp` is created next to the output and renamed when done. It is removed if the conversion fails. If the process is killed abruptly (power loss, `kill -9`), it can be left behind and is safe to delete.

Converting files from untrusted sources always carries some risk, because the decoding libraries (here, Pillow) parse them. Keep Pillow up to date.

## Installation

Requirements: Python 3.10 or newer. The project is not on PyPI yet, so install it from a clone of the repository:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install ".[image]"
```

The `image` extra installs [Pillow](https://python-pillow.org/), needed for PNG, JPG and WebP. Without it, only the CSV, JSON and text conversions are available (image formats simply do not show up).

This installs two commands: `lfconv` (command line) and `lfconv-gui` (window).

**Tkinter** is required for the window. It is usually included with Python on Windows and macOS. On Debian and Ubuntu install it with `sudo apt install python3-tk`.

Tested so far on Linux with Python 3.12. Windows and macOS are targets, but have not been tested yet.

## Using the window

```bash
lfconv-gui            # or: python -m lfconv.gui
```

1. **Add files…** or **Add folder…** (a folder adds the files directly inside it; hidden files and subfolders are ignored). Files that cannot be converted are ignored, and the status line says how many.
2. Pick **Convert to**. Only formats that the listed files can reach are offered, and files that cannot be converted to the chosen format are marked and skipped.
3. Optionally choose **Save in** (default: next to each original) and adjust the options that appear for the chosen format, such as quality.
4. Press **Convert**. Each row shows `Done: name.ext` or the reason it failed; select a failed row to read the details. By default existing files are not replaced; tick **Replace existing files** to allow it.

Drag and drop is planned (see the roadmap).

## Using the command line

```bash
lfconv photo.png --to webp                        # writes photo.webp next to the original
lfconv data.csv --to json
lfconv photo.png --to jpg --quality 70
lfconv ./images --to webp --output ./converted    # every convertible file in the folder
lfconv a.png b.jpg notes.txt --to pdf             # several inputs at once
lfconv --list                                     # what can be converted to what
lfconv --to webp --help                           # options of one output format
```

Main flags:

| Flag | Meaning |
|---|---|
| `--to FORMAT` | Output format (`jpeg` is accepted as `jpg`). Required. |
| `-o`, `--output DIR` | Folder for the results, created if needed. Default: next to each input. |
| `--overwrite` | Replace existing output files. |
| `--json` | Print one JSON object per line instead of text. |
| `-v`, `--verbose` | Show timings and the technical details of errors. |
| `--list` | List supported conversions (add `--json` for machine-readable output). |

Format options are generated from what each conversion declares, so `lfconv --to pdf --help` shows `--quality`, `--page-size` and `--font-size`. An option that does not apply to any of the files is rejected before anything is converted.

Behaviour worth knowing:

- Folders are not searched recursively. Hidden files and files that cannot be converted to the chosen format are skipped, and that is not an error.
- A file that fails does not stop the batch.
- If two inputs would produce the same output name (for example `a.png` and `a.webp` with `--to jpg`), the second one fails instead of overwriting the first.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Everything was converted (skipped files do not count as failures) |
| `1` | At least one file failed |
| `2` | Invalid usage, invalid option values, or nothing to convert |
| `130` | Interrupted with Ctrl-C |

With `--json`, each line is an event:

```json
{"event": "converted", "index": 1, "total": 2, "input": "a.csv", "output": "a.json"}
{"event": "failed", "index": 2, "total": 2, "input": "b.csv", "error": {"code": "invalid_file", "message": "Line 3 has 1 columns; expected 2."}}
{"event": "summary", "converted": 1, "failed": 1, "skipped": 0, "interrupted": false}
```

### From Python

```python
from lfconv import convert
from lfconv.converters import load_builtin_converters

load_builtin_converters()
convert("photo.png", "out/photo.webp", options={"quality": 80})
```

## Supported formats

| From | To | Notes |
|---|---|---|
| PNG, JPG, WebP | each other | `quality` (1–100, default 85) for JPG and WebP. Transparency is kept for PNG and WebP and flattened onto white for JPG. EXIF orientation is applied. Animated images keep only the first frame. WebP is limited to 16383 px per side. |
| PNG, JPG, WebP | PDF | One image per PDF. `quality` applies. The page has the size of the image in pixels at 72 dpi, and images are re-encoded as JPEG inside the PDF. |
| CSV | JSON | Streamed, so memory does not grow with file size. Values stay text (no type guessing). `delimiter`: `auto` (default), `,`, `;`, `tab`, `\|`. UTF-8 only (a BOM is accepted). |
| JSON | CSV | Needs a non-empty list of flat objects; nested values are rejected with a clear message. The whole JSON file is loaded in memory. `delimiter`: `,` (default), `;`, `tab`, `\|`. |
| JSON | TXT | Pretty-printed JSON. The whole file is loaded in memory. |
| TXT | PDF | UTF-8 text in Courier, streamed page by page. `page_size` (`a4` or `letter`), `font_size` (6–24, default 10). Characters outside Windows-1252 (emoji, CJK…) are replaced by `?`. Long lines wrap at the page width. |

Empty files are rejected. A file whose content does not match its extension (a JPEG named `.png`) is rejected with an explanatory message.

Planned, not yet scheduled: BMP, GIF, TIFF, AVIF, and combining several images into one PDF.

## Architecture

```text
src/lfconv/
├── core/         engine: formats, registry, options, errors, public API, batch planning
├── converters/   one module per kind of input: data.py, image.py, text.py (+ pdf_writer.py)
├── cli/          command-line interface
└── gui/          Tkinter window: model and worker (no Tk), widgets, messages
```

The rules that keep it maintainable:

- `core` knows nothing about Pillow, Tkinter or any specific format.
- The CLI and the GUI use only the public API of `core`, so neither contains conversion logic.
- Conversions are **registered**, and what is registered can be listed as plain data (`lfconv --list --json`). The GUI builds its controls from that description.
- The engine boundary is files in, files out: no Python objects cross the API. That is what makes replacing the engine with a Rust implementation a contained change.

See [docs/architecture.md](docs/architecture.md) for the details, how to add a converter and the Rust migration plan.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[image,dev]"
pytest
```

- `pytest -m "not slow"` skips the long-running tests (large files).
- The window tests need a display. They skip themselves without one. On a headless Linux machine run `xvfb-run -a pytest`.
- Contributions are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## Testing

The suite covers successful conversions, unsupported formats, missing, empty, corrupt and mislabelled files, permission errors, missing output folders, batches, option validation, atomic writes (a failure never leaves a partial file), streaming memory use, the CLI contract, the window logic and the window itself, and the no-network guarantee. PDFs are additionally checked against independent readers (`qpdf`, poppler and `pypdf`) during development.

Automated checks run on Linux only so far; there is no continuous integration yet.

## Benchmarks

**Not implemented yet** (planned for v0.4). The plan is to measure conversion time, peak memory, start-up time and installed size on reproducible synthetic data (for example 100 JPG → WebP, CSV ↔ JSON, 10 images → PDF) and to store the results so that a future Rust engine can be compared against them. Until those numbers exist, this project makes no performance claims beyond its design: no Electron, no background processes, streaming where the format allows it.

## Roadmap

- **v0.1 (current):** core engine, CLI, GUI, PNG/JPG/WebP, CSV/JSON, TXT and basic PDF, tests, sequential batches.
- **v0.2:** parallel batches, drag and drop, finer progress, cancellation, better error handling, configuration.
- **v0.3:** presets, compression, resizing, metadata options, custom rules.
- **v0.4:** benchmarks, profiling, optimisation, preparing the engine for Rust.
- **v1.0:** Rust engine, cross-platform binaries, Python vs Rust comparison, complete documentation.

Rust is only worth it where measurements say so; see the migration plan in [docs/architecture.md](docs/architecture.md).

## License

MIT, see [LICENSE](LICENSE). Contributions are accepted under the same license.
