"""Unified launcher for the Busylights menu bar app and settings GUI."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _app_root() -> Path:
    """Return the directory containing source files or bundled resources."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[1] / "Resources"
    return Path(__file__).resolve().parent


# Project root in source, Resources directory in a frozen macOS app bundle.
_ROOT = _app_root()


def _launch_args(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(_ROOT / "main.py"), *args]


def _is_app_bundle() -> bool:
    return bool(getattr(sys, "frozen", False)) or os.environ.get("BUSYLIGHT_APP_BUNDLE") == "1"


def _run_gui() -> None:
    from busylights_gui import main as gui_main

    gui_main()


def _run_menubar(*, launch_gui: bool = True) -> None:
    if sys.platform != "darwin":
        print("Busylights menu bar is macOS only. Use --gui for the settings window.")
        sys.exit(1)
    # On macOS, the menu bar item usually only appears when the app runs as a GUI process
    # (e.g. via pythonw), not from a terminal. Frozen app bundles are already GUI processes.
    if not getattr(sys, "frozen", False) and os.environ.get("BUSYLIGHT_SKIP_PYTHONW") != "1":
        exe_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(exe_dir, "pythonw")
        if os.path.isfile(pythonw) and "pythonw" not in sys.executable.lower():
            subprocess.Popen(
                [pythonw, str(_ROOT / "main.py"), "--menubar"],
                cwd=str(_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            if launch_gui:
                subprocess.Popen(
                    _launch_args("--gui"),
                    cwd=str(_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            return
    if launch_gui:
        subprocess.Popen(
            _launch_args("--gui"),
            cwd=str(_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    from busylights_menubar import main as menubar_main

    menubar_main()


def main() -> None:
    parser = argparse.ArgumentParser(description="Busylights launcher")
    parser.add_argument("--gui", action="store_true", help="Open settings GUI window")
    parser.add_argument("--menubar", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.gui:
        _run_gui()
        return

    _run_menubar(launch_gui=(not args.menubar and not _is_app_bundle()))


if __name__ == "__main__":
    main()
