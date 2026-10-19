# Contributing

Thanks for wanting to help. This project values small, readable, well-tested changes. By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

For anything bigger than a small fix, open an issue first to agree on the approach. The architecture is deliberately simple, and some ideas (a database, a web back end, Electron, telemetry) are out of scope by design.

## Setting up

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[image,dev]"
pytest
```

- `pytest -m "not slow"` skips the long-running tests.
- The window tests need a display and skip themselves without one. On a headless Linux machine use `xvfb-run -a pytest`. On Debian and Ubuntu, Tkinter comes from `sudo apt install python3-tk`.

## Ground rules

- **Privacy is a feature.** No network access, no telemetry, no collecting paths or file names. `tests/test_privacy.py` fails if a network module is imported.
- **Keep dependencies minimal.** Prefer the standard library. A new dependency needs a clear reason, a license that allows distributing the project under MIT (no AGPL, for example) and active maintenance. Say why in the pull request.
- **Keep the layers.** `core` knows no formats or interface. `cli` and `gui` contain no conversion logic. Read [docs/architecture.md](docs/architecture.md).
- **Conversions are files in, files out.** No Python objects crossing the public API; that keeps a future Rust engine possible.
- **Measure before optimising.** Performance changes need numbers before and after.
- **No premature features.** Do the roadmap in order and keep the MVP small.

## Code style

- Clear, idiomatic Python; type hints where they add value.
- Small functions, no duplicated code, no unnecessary classes.
- Comments only where the code cannot say why; no comments that restate the code.
- Code, comments, documentation and commit messages in English. User-visible window text goes in `gui/messages.py`.
- Errors shown to people must be understandable and must not expose tracebacks. Technical detail belongs in `__cause__` and `--verbose`.

## Adding a converter

See "Adding a converter" in [docs/architecture.md](docs/architecture.md). Every converter needs tests for:

- a valid conversion, checked on the output and not only on "no error";
- a wrong, corrupt or mislabelled input and an empty one;
- its options, including invalid values;
- a failure in the middle, which must leave no partial output;
- large inputs, marked `@pytest.mark.slow`, when the converter claims to stream.

Generate test files inside the test (`tmp_path`) instead of committing binaries.

## Pull requests

- Keep them small and focused, and describe what changed and why.
- Run the whole test suite. Add or update tests, and update the documentation and `CHANGELOG.md` when behaviour changes.
- For window changes, include a screenshot.
- Be explicit about what you tested and on which operating system. Windows and macOS testing is especially welcome, because automated checks only run on Linux so far.

## Reporting bugs

Please include:

- your operating system, Python version and `lfconv --version`;
- the exact command or the steps in the window;
- the output of the command with `--verbose`.

**Do not attach private files.** If a file triggers the problem, try to reproduce it with a small synthetic one.

## License

Contributions are accepted under the project's [MIT license](LICENSE).
