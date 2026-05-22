"""
Busylights settings window (Tkinter).

This GUI configures the menu bar app by updating the shared config file.
It does not run a separate light-control loop.
"""

from __future__ import annotations

import asyncio
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from busylights import (
    COLOR_OPTIONS,
    discover_devices,
    load_full_config,
    merge_discovered_into_config,
    save_full_config,
)
from mic_status import is_recording

BRIGHTNESS_OPTIONS = (0, 25, 50, 75, 100)


def _normalize_device(d: dict) -> dict | None:
    """Return normalized device dict or None when invalid."""
    if not isinstance(d, dict) or not d.get("fingerprint") or not d.get("ip") or not d.get("sku"):
        return None
    return {
        "fingerprint": d["fingerprint"],
        "ip": d["ip"],
        "sku": d["sku"],
        "enabled": d.get("enabled", True),
    }


class BusylightsGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Busylights Settings")
        self.root.geometry("640x760")

        self.device_checkboxes: dict[str, dict] = {}

        self.mode_var = tk.StringVar(value="auto")
        self.busy_color_var = tk.StringVar(value="Red")
        self.available_color_var = tk.StringVar(value="Green")
        self.manual_color_var = tk.StringVar(value="Green")
        self.busy_brightness_var = tk.StringVar(value="50")
        self.available_brightness_var = tk.StringVar(value="50")
        self.manual_brightness_var = tk.StringVar(value="50")

        self._create_widgets()
        self._load_config_into_ui()
        self._poll_mic_status()

    def _create_widgets(self) -> None:
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        title_label = ttk.Label(main_frame, text="Busylights Settings", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))

        mode_frame = ttk.LabelFrame(main_frame, text="Mode", padding="10")
        mode_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Radiobutton(
            mode_frame,
            text="Auto (mic based)",
            variable=self.mode_var,
            value="auto",
            command=self._on_setting_change,
        ).grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Radiobutton(
            mode_frame,
            text="Manual (override color)",
            variable=self.mode_var,
            value="manual",
            command=self._on_setting_change,
        ).grid(row=1, column=0, sticky=tk.W, padx=5)
        ttk.Radiobutton(
            mode_frame,
            text="Off",
            variable=self.mode_var,
            value="off",
            command=self._on_setting_change,
        ).grid(row=2, column=0, sticky=tk.W, padx=5)

        devices_frame = ttk.LabelFrame(main_frame, text="Devices", padding="10")
        devices_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        button_row = ttk.Frame(devices_frame)
        button_row.grid(row=0, column=0, columnspan=2, pady=5)
        ttk.Button(button_row, text="Scan for Devices", command=self._scan_devices).grid(row=0, column=0, padx=5)
        ttk.Button(button_row, text="Save Config", command=self._on_save_clicked).grid(row=0, column=1, padx=5)

        checkbox_frame = ttk.Frame(devices_frame)
        checkbox_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        canvas = tk.Canvas(checkbox_frame, height=140)
        scrollbar = ttk.Scrollbar(checkbox_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.device_checkbox_frame = scrollable_frame

        colors_frame = ttk.LabelFrame(main_frame, text="Colors", padding="10")
        colors_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        color_names = [name for name, _ in COLOR_OPTIONS]
        brightness_values = [str(pct) for pct in BRIGHTNESS_OPTIONS]

        ttk.Label(colors_frame, text="Busy color:").grid(row=0, column=0, sticky=tk.W, padx=5)
        busy_combo = ttk.Combobox(colors_frame, textvariable=self.busy_color_var, values=color_names, state="readonly", width=15)
        busy_combo.grid(row=0, column=1, padx=5)
        busy_combo.bind("<<ComboboxSelected>>", lambda _: self._on_setting_change())

        ttk.Label(colors_frame, text="Busy brightness:").grid(row=0, column=2, sticky=tk.W, padx=(15, 5))
        busy_br_combo = ttk.Combobox(
            colors_frame,
            textvariable=self.busy_brightness_var,
            values=brightness_values,
            state="readonly",
            width=8,
        )
        busy_br_combo.grid(row=0, column=3, padx=5)
        busy_br_combo.bind("<<ComboboxSelected>>", lambda _: self._on_setting_change())

        ttk.Label(colors_frame, text="Available color:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        available_combo = ttk.Combobox(
            colors_frame,
            textvariable=self.available_color_var,
            values=color_names,
            state="readonly",
            width=15,
        )
        available_combo.grid(row=1, column=1, padx=5, pady=5)
        available_combo.bind("<<ComboboxSelected>>", lambda _: self._on_setting_change())

        ttk.Label(colors_frame, text="Available brightness:").grid(row=1, column=2, sticky=tk.W, padx=(15, 5), pady=5)
        available_br_combo = ttk.Combobox(
            colors_frame,
            textvariable=self.available_brightness_var,
            values=brightness_values,
            state="readonly",
            width=8,
        )
        available_br_combo.grid(row=1, column=3, padx=5, pady=5)
        available_br_combo.bind("<<ComboboxSelected>>", lambda _: self._on_setting_change())

        ttk.Label(colors_frame, text="Manual color:").grid(row=2, column=0, sticky=tk.W, padx=5)
        manual_combo = ttk.Combobox(
            colors_frame,
            textvariable=self.manual_color_var,
            values=color_names,
            state="readonly",
            width=15,
        )
        manual_combo.grid(row=2, column=1, padx=5)
        manual_combo.bind("<<ComboboxSelected>>", lambda _: self._on_setting_change())

        ttk.Label(colors_frame, text="Manual brightness:").grid(row=2, column=2, sticky=tk.W, padx=(15, 5))
        manual_br_combo = ttk.Combobox(
            colors_frame,
            textvariable=self.manual_brightness_var,
            values=brightness_values,
            state="readonly",
            width=8,
        )
        manual_br_combo.grid(row=2, column=3, padx=5)
        manual_br_combo.bind("<<ComboboxSelected>>", lambda _: self._on_setting_change())

        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        self.mode_status_label = ttk.Label(status_frame, text="Mode: auto", font=("Arial", 10))
        self.mode_status_label.grid(row=0, column=0, sticky=tk.W, pady=3)

        self.mic_status_label = ttk.Label(status_frame, text="Recording: unknown", font=("Arial", 10))
        self.mic_status_label.grid(row=1, column=0, sticky=tk.W, pady=3)

        info = "This window edits config used by the menu bar app."
        self.app_status_label = ttk.Label(status_frame, text=info, font=("Arial", 10))
        self.app_status_label.grid(row=2, column=0, sticky=tk.W, pady=3)

        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        main_frame.rowconfigure(5, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        devices_frame.columnconfigure(0, weight=1)
        colors_frame.columnconfigure(1, weight=1)

    def _log(self, message: str) -> None:
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def _load_config_into_ui(self) -> None:
        config = load_full_config()

        self.mode_var.set(config.get("mode", "auto"))
        self.busy_color_var.set(config.get("active_color", "Red"))
        self.available_color_var.set(config.get("inactive_color", "Green"))
        self.manual_color_var.set(config.get("manual_color", "Green"))
        self.busy_brightness_var.set(str(max(0, min(100, config.get("active_brightness", 50)))))
        self.available_brightness_var.set(str(max(0, min(100, config.get("inactive_brightness", 50)))))
        self.manual_brightness_var.set(str(max(0, min(100, config.get("manual_brightness", 50)))))

        self._refresh_device_list()
        self._update_status_labels()

    def _refresh_device_list(self) -> None:
        for widget in self.device_checkbox_frame.winfo_children():
            widget.destroy()
        self.device_checkboxes.clear()

        config = load_full_config()
        devices = config.get("devices", [])

        row = 0
        for device in devices:
            if _normalize_device(device):
                label = f"{device.get('sku', 'Unknown')} at {device.get('ip', 'Unknown')}"
                var = tk.BooleanVar(value=device.get("enabled", True))
                checkbox = ttk.Checkbutton(
                    self.device_checkbox_frame,
                    text=label,
                    variable=var,
                    command=self._on_device_toggle,
                )
                checkbox.grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)

                self.device_checkboxes[device.get("fingerprint")] = {
                    "var": var,
                    "device": device,
                    "checkbox": checkbox,
                }
                row += 1

    def _scan_devices(self) -> None:
        self._log("Scanning for devices...")

        def scan_thread() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                devices = loop.run_until_complete(discover_devices())
                loop.close()

                if devices:
                    config = load_full_config()
                    config["devices"] = merge_discovered_into_config(config, devices)
                    save_full_config(config)
                    device_count = len(devices)
                    self.root.after(0, lambda count=device_count: self._log(f"Found {count} device(s)"))
                    self.root.after(0, self._refresh_device_list)
                else:
                    self.root.after(0, lambda: self._log("No devices found. Enable Local API in the Govee app."))
            except Exception as e:  # pragma: no cover - UI path
                self.root.after(0, lambda: self._log(f"Error scanning devices: {e}"))

        threading.Thread(target=scan_thread, daemon=True).start()

    def _coerce_brightness(self, value: str) -> int:
        try:
            return max(0, min(100, int(value)))
        except ValueError:
            return 50

    def _save_config(self, *, should_log: bool) -> None:
        config = load_full_config()

        config["mode"] = self.mode_var.get()
        config["active_color"] = self.busy_color_var.get()
        config["inactive_color"] = self.available_color_var.get()
        config["manual_color"] = self.manual_color_var.get()
        config["active_brightness"] = self._coerce_brightness(self.busy_brightness_var.get())
        config["inactive_brightness"] = self._coerce_brightness(self.available_brightness_var.get())
        config["manual_brightness"] = self._coerce_brightness(self.manual_brightness_var.get())

        devices = config.get("devices", [])
        for device in devices:
            fingerprint = device.get("fingerprint")
            if fingerprint in self.device_checkboxes:
                device["enabled"] = self.device_checkboxes[fingerprint]["var"].get()

        config["devices"] = devices
        save_full_config(config)
        self._update_status_labels()
        if should_log:
            self._log("Configuration saved")

    def _update_status_labels(self) -> None:
        self.mode_status_label.config(text=f"Mode: {self.mode_var.get()}")

    def _on_device_toggle(self) -> None:
        self._save_config(should_log=False)

    def _on_setting_change(self) -> None:
        self._save_config(should_log=False)

    def _on_save_clicked(self) -> None:
        self._save_config(should_log=True)

    def _poll_mic_status(self) -> None:
        try:
            busy = is_recording()
            status = "busy" if busy else "available"
            self.mic_status_label.config(text=f"Recording: {status}")
        except Exception:
            self.mic_status_label.config(text="Recording: unknown")
        self.root.after(2000, self._poll_mic_status)

    def on_closing(self) -> None:
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = BusylightsGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
