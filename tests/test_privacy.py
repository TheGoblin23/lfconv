"""The README promises that nothing leaves the device. These tests keep that promise honest."""

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

NETWORK_MODULES = {
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib",
    "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "webbrowser", "asyncio", "socketserver",
}


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def test_source_never_imports_a_network_module():
    offenders = {
        str(path.relative_to(SRC)): sorted(set(imported_modules(path)) & NETWORK_MODULES)
        for path in SRC.rglob("*.py")
    }
    assert {path: found for path, found in offenders.items() if found} == {}


def test_a_full_conversion_never_loads_a_network_module(tmp_path):
    """Run the real code path in a fresh interpreter and inspect what got imported.

    ``urllib.parse`` is allowed: the standard library's ``pathlib`` loads it, and it
    only parses text. ``urllib.request`` and the rest can open connections.
    """
    forbidden = (NETWORK_MODULES - {"urllib"}) | {"urllib.request"}
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    code = (
        "import sys\n"
        "from lfconv.cli.main import main\n"
        "main(['data.csv', '--to', 'json'])\n"
        f"bad = sorted(m for m in sys.modules if m in {sorted(forbidden)!r} or m.split('.')[0] in {sorted(forbidden)!r})\n"
        "print('NETWORK:', bad)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path,
        env={"PYTHONPATH": str(SRC), "PATH": ""}, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("NETWORK: []"), result.stdout
