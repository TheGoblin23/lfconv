# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow [Semantic Versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Added

- Core engine: format normalisation, converter registry that can be listed as plain data, option declarations and validation, error hierarchy with stable error codes, and `convert()` with atomic writes.
- Image conversions between PNG, JPG and WebP, and image to PDF (Pillow, optional `image` extra).
- Data conversions: CSV to JSON (streaming), JSON to CSV, JSON to text.
- Text to PDF with a built-in minimal PDF writer (no dependencies, streaming, no metadata, deterministic output).
- Command-line tool `lfconv`: files and folders, `--output`, `--overwrite`, `--verbose`, `--json` events, `--list`, per-format options, defined exit codes.
- Desktop window `lfconv-gui` (Tkinter): file and folder selection, format and option controls generated from the registry, background conversion with progress, per-file status and clear error messages.
- Tests for the engine, converters, CLI, window logic and window, plus tests that enforce the no-network guarantee.
- Documentation: README, architecture guide, contributing guide, code of conduct.

### Known limitations

- Tested on Linux with Python 3.12 only.
- Text input must be UTF-8; PDF output from text supports Windows-1252 characters only.
- JSON conversions load the whole file in memory.
- No drag and drop, cancellation button or parallel batches yet.
