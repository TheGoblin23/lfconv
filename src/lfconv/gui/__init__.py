import sys


def main() -> int:
    """Open the converter window."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(
            "Tkinter is not available. On Debian/Ubuntu install it with: sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 1
    from .app import run

    return run()
