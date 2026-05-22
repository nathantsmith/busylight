"""
Menu bar app for Busylights: Auto (mic logic), Manual mode, Settings (Free/Busy/Override colors).
Uses same config as CLI/GUI. Icons for Auto, Manual, Settings.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

import rumps

from busylights import (
    CONFIG_JSON,
    COLOR_NAME_TO_RGB,
    COLOR_OPTIONS,
    load_full_config,
    run_loop,
    save_full_config,
)


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[1] / "Resources"
    return Path(__file__).resolve().parent


def _launch_args(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(_DIR / "main.py"), *args]


_DIR = _resource_root()
# On Air style: outline (idle) vs filled (recording)
ICON_PATH_IDLE = _DIR / "assets" / "menubar_icon_idle.png"
ICON_PATH_ACTIVE = _DIR / "assets" / "menubar_icon_active.png"
ICON_PATH = _DIR / "assets" / "menubar_icon.png"  # fallback
ICON_AUTO = _DIR / "assets" / "icon_auto.png"
ICON_MANUAL = _DIR / "assets" / "icon_manual.png"
ICON_SETTINGS = _DIR / "assets" / "icon_settings.png"

# Shared state for mode, colors, and brightness (read by background loop, written by menu)
_state_lock = threading.Lock()
_mode = "auto"
_manual_color = "Green"
_active_color = "Red"
_inactive_color = "Green"
_active_brightness = 50
_inactive_brightness = 50
_manual_brightness = 50
_current_busy: bool | None = None
_last_config_mtime: float | None = None

BRIGHTNESS_OPTIONS = (0, 25, 50, 75, 100)  # 0% = off


def _status_icon_path(active: bool = False) -> str | None:
    path = ICON_PATH_ACTIVE if active else ICON_PATH_IDLE
    if path.exists():
        return str(path.resolve())
    if ICON_PATH.exists():
        return str(ICON_PATH.resolve())
    return None


def _get_mode_rgb() -> tuple[str, tuple[int, int, int] | None, tuple[int, int, int], tuple[int, int, int], int, int, int]:
    _refresh_state_from_config_if_changed()
    with _state_lock:
        manual_rgb = COLOR_NAME_TO_RGB.get(_manual_color, (0, 255, 0))
        active_rgb = COLOR_NAME_TO_RGB.get(_active_color, (255, 0, 0))
        inactive_rgb = COLOR_NAME_TO_RGB.get(_inactive_color, (0, 255, 0))
        a_br = max(0, min(100, _active_brightness))
        i_br = max(0, min(100, _inactive_brightness))
        m_br = max(0, min(100, _manual_brightness))
        return (_mode, manual_rgb, active_rgb, inactive_rgb, a_br, i_br, m_br)


def _set_status(busy: bool) -> None:
    with _state_lock:
        global _current_busy
        _current_busy = busy


def _apply_config_to_state(config: dict) -> None:
    with _state_lock:
        global _mode, _manual_color, _active_color, _inactive_color
        global _active_brightness, _inactive_brightness, _manual_brightness
        _mode = config.get("mode", "auto")
        _manual_color = config.get("manual_color", "Green")
        _active_color = config.get("active_color", "Red")
        _inactive_color = config.get("inactive_color", "Green")
        _active_brightness = max(0, min(100, config.get("active_brightness", 50)))
        _inactive_brightness = max(0, min(100, config.get("inactive_brightness", 50)))
        _manual_brightness = max(0, min(100, config.get("manual_brightness", 50)))


def _refresh_state_from_config_if_changed() -> None:
    global _last_config_mtime
    try:
        current_mtime = os.path.getmtime(CONFIG_JSON)
    except OSError:
        current_mtime = None
    if current_mtime is None or _last_config_mtime == current_mtime:
        return
    _last_config_mtime = current_mtime
    _apply_config_to_state(load_full_config())


def _run_loop_thread() -> None:
    try:
        asyncio.run(run_loop(on_status_change=_set_status, get_mode_rgb=_get_mode_rgb))
    except Exception:
        pass


class BusylightsMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(
            name="Busylights",
            title="",
            icon=_status_icon_path(False),
            template=True,
            quit_button=None,
        )
        self._thread: threading.Thread | None = None
        self._load_state_from_config()
        self._auto_item = rumps.MenuItem("Auto", callback=self._on_auto)
        self._manual_item = rumps.MenuItem("Manual", callback=self._on_manual)
        self._off_item = rumps.MenuItem("Off", callback=self._on_off)
        menu_icon_size = (16, 16)
        if ICON_AUTO.exists():
            self._auto_item.set_icon(str(ICON_AUTO.resolve()), dimensions=menu_icon_size, template=False)
        if ICON_MANUAL.exists():
            self._manual_item.set_icon(str(ICON_MANUAL.resolve()), dimensions=menu_icon_size, template=False)
        settings = rumps.MenuItem("Settings")
        if ICON_SETTINGS.exists():
            settings.set_icon(str(ICON_SETTINGS.resolve()), dimensions=menu_icon_size, template=False)
        free_sub = rumps.MenuItem("Free Color")
        busy_sub = rumps.MenuItem("Busy Color")
        override_sub = rumps.MenuItem("Override color")
        for name, _ in COLOR_OPTIONS:
            free_sub.add(rumps.MenuItem(name, callback=self._on_free_color))
            busy_sub.add(rumps.MenuItem(name, callback=self._on_busy_color))
            override_sub.add(rumps.MenuItem(name, callback=self._on_override_color))
        settings.add(free_sub)
        settings.add(busy_sub)
        settings.add(override_sub)
        free_br_sub = rumps.MenuItem("Free Brightness")
        busy_br_sub = rumps.MenuItem("Busy Brightness")
        override_br_sub = rumps.MenuItem("Override Brightness")
        for pct in BRIGHTNESS_OPTIONS:
            free_br_sub.add(rumps.MenuItem(f"{pct}%", callback=self._on_free_brightness))
            busy_br_sub.add(rumps.MenuItem(f"{pct}%", callback=self._on_busy_brightness))
            override_br_sub.add(rumps.MenuItem(f"{pct}%", callback=self._on_override_brightness))
        settings.add(free_br_sub)
        settings.add(busy_br_sub)
        settings.add(override_br_sub)
        self.menu = [
            self._auto_item,
            self._manual_item,
            self._off_item,
            settings,
            None,
            "Open GUI",
            "Quit",
        ]
        self._refresh_checkmarks()

    def _load_state_from_config(self) -> None:
        global _last_config_mtime
        _apply_config_to_state(load_full_config())
        try:
            _last_config_mtime = os.path.getmtime(CONFIG_JSON)
        except OSError:
            _last_config_mtime = None

    def _save_config(self) -> None:
        config = load_full_config()
        with _state_lock:
            config["mode"] = _mode
            config["manual_color"] = _manual_color
            config["active_color"] = _active_color
            config["inactive_color"] = _inactive_color
            config["active_brightness"] = _active_brightness
            config["inactive_brightness"] = _inactive_brightness
            config["manual_brightness"] = _manual_brightness
        save_full_config(config)
        global _last_config_mtime
        try:
            _last_config_mtime = os.path.getmtime(CONFIG_JSON)
        except OSError:
            _last_config_mtime = None

    def _refresh_checkmarks(self) -> None:
        with _state_lock:
            mode = _mode
        self._auto_item.state = 1 if mode == "auto" else 0
        self._manual_item.state = 1 if mode == "manual" else 0
        self._off_item.state = 1 if mode == "off" else 0

    def _on_auto(self, _: rumps.MenuItem) -> None:
        with _state_lock:
            global _mode
            _mode = "auto"
        self._save_config()
        self._refresh_checkmarks()

    def _on_manual(self, _: rumps.MenuItem) -> None:
        with _state_lock:
            global _mode
            _mode = "manual"
        self._save_config()
        self._refresh_checkmarks()

    def _on_off(self, _: rumps.MenuItem) -> None:
        with _state_lock:
            global _mode
            _mode = "off"
        self._save_config()
        self._refresh_checkmarks()

    def _on_free_color(self, sender: rumps.MenuItem) -> None:
        name = sender.title
        with _state_lock:
            global _inactive_color
            _inactive_color = name
        self._save_config()

    def _on_busy_color(self, sender: rumps.MenuItem) -> None:
        name = sender.title
        with _state_lock:
            global _active_color
            _active_color = name
        self._save_config()

    def _on_override_color(self, sender: rumps.MenuItem) -> None:
        name = sender.title
        with _state_lock:
            global _mode, _manual_color
            _mode = "manual"
            _manual_color = name
        self._save_config()
        self._refresh_checkmarks()

    def _parse_brightness(self, title: str) -> int:
        try:
            return max(0, min(100, int(title.rstrip("%"))))
        except ValueError:
            return 50

    def _on_free_brightness(self, sender: rumps.MenuItem) -> None:
        with _state_lock:
            global _inactive_brightness
            _inactive_brightness = self._parse_brightness(sender.title)
        self._save_config()

    def _on_busy_brightness(self, sender: rumps.MenuItem) -> None:
        with _state_lock:
            global _active_brightness
            _active_brightness = self._parse_brightness(sender.title)
        self._save_config()

    def _on_override_brightness(self, sender: rumps.MenuItem) -> None:
        with _state_lock:
            global _manual_brightness
            _manual_brightness = self._parse_brightness(sender.title)
        self._save_config()

    @rumps.clicked("Open GUI")
    def open_gui(self, _: rumps.MenuItem) -> None:
        subprocess.Popen(
            _launch_args("--gui"),
            cwd=str(_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @rumps.clicked("Quit")
    def quit_app(self, _: rumps.MenuItem) -> None:
        rumps.quit_application()

    def _update_title_and_menu(self, _: object) -> None:
        _refresh_state_from_config_if_changed()
        self._refresh_checkmarks()
        with _state_lock:
            mode = _mode
            busy = _current_busy
        self.icon = _status_icon_path(mode == "auto" and busy is True)
        self.title = ""

    def run(self, *args: object, **kwargs: object) -> None:
        self._refresh_checkmarks()
        self._thread = threading.Thread(target=_run_loop_thread, daemon=True)
        self._thread.start()
        rumps.Timer(self._update_title_and_menu, interval=1.0).start()
        super().run(*args, **kwargs)


def main() -> None:
    if sys.platform != "darwin":
        print("Menu bar app is macOS only.", file=sys.stderr)
        sys.exit(1)
    app = BusylightsMenuBarApp()
    app.run()


if __name__ == "__main__":
    main()
