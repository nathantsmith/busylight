"""
Discover a Govee light and update its color every few seconds based on meeting
status (mic in use = busy = red, mic idle = available = green).

Requires Govee Local API to be enabled on the device (see Govee app WLAN guide).
macOS only (uses CoreAudio for mic status).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Callable


from govee_local_api import GoveeController, GoveeDevice

from mic_status import is_recording

CHECK_INTERVAL = 3  # seconds between status checks
# Delay between UDP commands so the device processes each one (avoids dropped "available" color)
COMMAND_DELAY = 0.25

# Color options for active (busy) / inactive (available) dropdowns: (display_name, rgb_tuple)
COLOR_OPTIONS: list[tuple[str, tuple[int, int, int]]] = [
    ("Red", (255, 0, 0)),
    ("Green", (0, 255, 0)),
    ("Blue", (0, 0, 255)),
    ("Yellow", (255, 255, 0)),
    ("Orange", (255, 165, 0)),
    ("Purple", (128, 0, 128)),
    ("White", (255, 255, 255)),
]
COLOR_NAME_TO_RGB = {name: rgb for name, rgb in COLOR_OPTIONS}

# Discovery: only when --discover or --config is passed
DISCOVERY_PROBE_COUNT = 6   # more probes = better chance to see all devices
DISCOVERY_POLL_INTERVAL = 2  # sec between probes
DISCOVERY_SETTLE_SECONDS = 2  # wait after last probe for late UDP responses

CONFIG_DIR = Path.home() / ".config" / "busylight"
CONFIG_FILE = CONFIG_DIR / "device"  # legacy single-device file
CONFIG_JSON = CONFIG_DIR / "config.json"


def _normalize_device(d: dict) -> dict | None:
    """Return dict with fingerprint, ip, sku, enabled; or None if invalid."""
    if not isinstance(d, dict) or not d.get("fingerprint") or not d.get("ip") or not d.get("sku"):
        return None
    return {
        "fingerprint": d["fingerprint"],
        "ip": d["ip"],
        "sku": d["sku"],
        "enabled": d.get("enabled", True),  # legacy: no key => enabled
    }


def load_full_config() -> dict:
    """Load config: devices, colors, brightnesses, mode ('auto'|'manual'), manual_color."""
    data: dict = {
        "devices": [],
        "active_color": "Red",
        "inactive_color": "Green",
        "mode": "auto",
        "manual_color": "Green",
        "active_brightness": 50,
        "inactive_brightness": 50,
        "manual_brightness": 50,
    }
    if CONFIG_JSON.exists():
        try:
            raw = json.loads(CONFIG_JSON.read_text())
            raw_devices = raw.get("devices") or []
            data["devices"] = [d for d in (_normalize_device(x) for x in raw_devices) if d]
            data["active_color"] = raw.get("active_color") or data["active_color"]
            data["inactive_color"] = raw.get("inactive_color") or data["inactive_color"]
            data["mode"] = raw.get("mode") or data["mode"]
            data["manual_color"] = raw.get("manual_color") or data["manual_color"]
            data["active_brightness"] = raw.get("active_brightness", data["active_brightness"])
            data["inactive_brightness"] = raw.get("inactive_brightness", data["inactive_brightness"])
            data["manual_brightness"] = raw.get("manual_brightness", data["manual_brightness"])
        except (OSError, json.JSONDecodeError):
            pass
    elif CONFIG_FILE.exists():
        try:
            device_id = CONFIG_FILE.read_text().strip()
            if device_id:
                data["devices"] = [{"fingerprint": device_id, "ip": "", "sku": "", "enabled": True}]  # legacy
        except OSError:
            pass
    return data


def save_full_config(data: dict) -> None:
    """Save devices, colors, brightnesses, mode, and manual_color to config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_JSON.write_text(
        json.dumps(
            {
                "devices": data.get("devices", []),
                "active_color": data.get("active_color", "Red"),
                "inactive_color": data.get("inactive_color", "Green"),
                "mode": data.get("mode", "auto"),
                "manual_color": data.get("manual_color", "Green"),
                "active_brightness": data.get("active_brightness", 50),
                "inactive_brightness": data.get("inactive_brightness", 50),
                "manual_brightness": data.get("manual_brightness", 50),
            },
            indent=2,
        )
    )


def merge_discovered_into_config(config: dict, discovered: list[GoveeDevice]) -> list[dict]:
    """Merge discovered devices into config devices list. Existing by fingerprint get ip/sku updated; new get enabled: false. Returns updated devices list."""
    by_fp = {d["fingerprint"]: dict(d) for d in (config.get("devices") or []) if _normalize_device(d)}
    for d in discovered:
        if d.fingerprint in by_fp:
            by_fp[d.fingerprint].update({"ip": d.ip, "sku": d.sku})
        else:
            by_fp[d.fingerprint] = {"fingerprint": d.fingerprint, "ip": d.ip, "sku": d.sku, "enabled": False}
    return list(by_fp.values())


def _is_ip(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


async def discover_devices(probe_count: int | None = None) -> list[GoveeDevice]:
    """Discover Govee devices and return the list (controller is cleaned up).
    probe_count: number of probes (default DISCOVERY_PROBE_COUNT). Only used for --discover / --config.
    """
    n = probe_count if probe_count is not None else DISCOVERY_PROBE_COUNT
    # discovery_enabled=False: we send probes ourselves; avoid timer firing after cleanup()
    controller = GoveeController(
        discovery_enabled=False,
        update_enabled=False,
    )
    await controller.start()
    print(f"Discovering Govee devices ({n} probe{'s' if n != 1 else ''}, every {DISCOVERY_POLL_INTERVAL}s)...")
    probe = 0
    while probe < n:
        controller.send_discovery_message()
        probe += 1
        await asyncio.sleep(DISCOVERY_POLL_INTERVAL)
        devices = controller.devices
        print(f"  probe {probe}/{n}: {len(devices)} device(s) — {[f'{d.sku}@{d.ip}' for d in devices]}")
    # Let late UDP responses arrive before reading final list
    if DISCOVERY_SETTLE_SECONDS > 0:
        await asyncio.sleep(DISCOVERY_SETTLE_SECONDS)
        devices = controller.devices
        print(f"  (after {DISCOVERY_SETTLE_SECONDS}s settle: {len(devices)} device(s))")
    devices = controller.devices
    controller.cleanup()
    return devices


async def run_discover() -> None:
    """Discover (scan), merge into config.json available lights, and print. Only runs when --discover is passed."""
    config = load_full_config()
    devices = await discover_devices()
    if not devices:
        print("No Govee devices found. Enable Local API in the Govee app.")
        return
    config["devices"] = merge_discovered_into_config(config, devices)
    save_full_config(config)
    print(f"Found {len(devices)} device(s) (saved to config as available lights):\n")
    if len(devices) == 1:
        print("  Tip: If you have more lights, ensure they're on the same Wi‑Fi and LAN control is on in the Govee app.\n")
    for i, d in enumerate(devices, 1):
        print(f"  {i}. {d.sku}")
        print(f"     IP: {d.ip}")
        print(f"     fingerprint: {d.fingerprint}")
        print()


async def choose_device() -> bool:
    """Prompt for multi-select (enable/disable) and colors; save to config. Scan only if no available lights in config."""
    import inquirer

    config = load_full_config()
    available = [d for d in (config.get("devices") or []) if _normalize_device(d)]

    if not available:
        # No available lights in config: scan and merge into config
        devices = await discover_devices()
        if not devices:
            print("No Govee devices found. Enable Local API in the Govee app.")
            return False
        config["devices"] = merge_discovered_into_config(config, devices)
        save_full_config(config)
        available = config["devices"]

    # Multiselect: choices = all available lights; default = enabled ones. Save only updates enabled.
    device_choices = [(f"{d['sku']} at {d['ip']}", d["fingerprint"]) for d in available]
    checkbox_default = [d["fingerprint"] for d in available if d.get("enabled", True)]
    color_choices = [name for name, _ in COLOR_OPTIONS]
    questions = [
        inquirer.Checkbox(
            "devices",
            message="Which light(s) should show meeting status? (space to toggle, enter to confirm)",
            choices=device_choices,
            default=checkbox_default,
        ),
        inquirer.List(
            "active_color",
            message="Color when busy (mic in use)?",
            choices=color_choices,
            default=config.get("active_color") or "Red",
        ),
        inquirer.List(
            "inactive_color",
            message="Color when available?",
            choices=color_choices,
            default=config.get("inactive_color") or "Green",
        ),
    ]
    answers = inquirer.prompt(questions)
    if answers is None:
        print("Cancelled.")
        return False
    # Update enabled from checkbox selection; keep full device list
    selected_fps = set(answers.get("devices") or [])
    for d in available:
        d["enabled"] = d["fingerprint"] in selected_fps
    save_full_config({
        "devices": available,
        "active_color": answers.get("active_color", config["active_color"]),
        "inactive_color": answers.get("inactive_color", config["inactive_color"]),
    })
    enabled_labels = [f"{d['sku']} at {d['ip']}" for d in available if d.get("enabled")]
    print(f"Enabled {len(enabled_labels)} device(s): {', '.join(enabled_labels) or '(none)'}")
    print(f"Colors: busy={answers.get('active_color')}, available={answers.get('inactive_color')}")
    print("Run without --config to use these settings.")
    return True


def _find_device(controller: GoveeController, device_id: str) -> GoveeDevice | None:
    """Resolve device_id (IP, fingerprint, or SKU) to a GoveeDevice, or None if not present."""
    key = device_id.strip()
    if not key:
        return None
    if _is_ip(key):
        return controller.get_device_by_ip(key)
    dev = controller.get_device_by_fingerprint(key)
    if dev is not None:
        return dev
    return controller.get_device_by_sku(key)


async def _apply_color_to_device(
    controller: GoveeController,
    device: GoveeDevice,
    rgb: tuple[int, int, int],
    brightness: int = 50,
) -> None:
    """Send on/off, brightness, and color with short delays. When brightness is 0, turn the light off explicitly."""
    brightness = max(0, min(100, brightness))
    if brightness == 0:
        await controller.turn_on_off(device, False)
        return
    await controller.turn_on_off(device, True)
    await asyncio.sleep(COMMAND_DELAY)
    await controller.set_brightness(device, brightness)
    await asyncio.sleep(COMMAND_DELAY)
    await controller.set_color(device, rgb=rgb, temperature=None)
    await asyncio.sleep(COMMAND_DELAY)
    # Send color again; devices often drop the last command in a quick burst
    await controller.set_color(device, rgb=rgb, temperature=None)


async def run_loop(
    on_status_change: Callable[[bool], None] | None = None,
    get_mode_rgb: (
        Callable[
            [],
            tuple[
                str,
                tuple[int, int, int] | None,
                tuple[int, int, int],
                tuple[int, int, int],
                int,
                int,
                int,
            ],
        ]
        | None
    ) = None,
) -> bool:
    """Returns False if no devices. get_mode_rgb returns (mode, manual_rgb, active_rgb, inactive_rgb, active_brightness, inactive_brightness, manual_brightness)."""
    config = load_full_config()
    device_entries = config.get("devices") or []
    valid_entries = [
        e for e in device_entries
        if isinstance(e, dict) and e.get("ip") and e.get("sku") and e.get("fingerprint") and e.get("enabled", True)
    ]
    if not valid_entries:
        print("No devices enabled. Run --discover to scan, then --config to enable device(s) and set colors.")
        return False

    controller = GoveeController(
        discovery_enabled=False,
        update_enabled=False,
    )
    await controller.start()

    for entry in valid_entries:
        controller.add_device(entry["ip"], entry["sku"], entry["fingerprint"], None)
    selected_devices = controller.devices
    active_rgb = COLOR_NAME_TO_RGB.get(config["active_color"], (255, 0, 0))
    inactive_rgb = COLOR_NAME_TO_RGB.get(config["inactive_color"], (0, 255, 0))
    active_brightness = max(0, min(100, config.get("active_brightness", 50)))
    inactive_brightness = max(0, min(100, config.get("inactive_brightness", 50)))
    manual_brightness = max(0, min(100, config.get("manual_brightness", 50)))

    print(f"Using {len(selected_devices)} device(s): {', '.join(f'{d.sku}@{d.ip}' for d in selected_devices)}")
    print(f"Colors: busy={config['active_color']}, available={config['inactive_color']}")
    if get_mode_rgb:
        print("Mode: driven by menu bar (Auto/Manual)")
    else:
        print(f"Checking meeting status every {CHECK_INTERVAL}s (Ctrl+C to stop).\n")

    # Resolve initial RGB and brightness from mode when using get_mode_rgb
    if get_mode_rgb:
        mode, m_rgb, a_rgb, i_rgb, a_br, i_br, m_br = get_mode_rgb()
        if mode == "off":
            initial_rgb = inactive_rgb
            initial_brightness = 0
            initial_status = "off"
        elif mode == "manual" and m_rgb is not None:
            initial_rgb = m_rgb
            initial_brightness = max(0, min(100, m_br))
            initial_status = "manual"
        else:
            initial_busy = is_recording()
            initial_rgb = a_rgb if initial_busy else i_rgb
            initial_brightness = a_br if initial_busy else i_br
            initial_brightness = max(0, min(100, initial_brightness))
            initial_status = "busy" if initial_busy else "available"
    else:
        initial_busy = is_recording()
        initial_rgb = active_rgb if initial_busy else inactive_rgb
        initial_brightness = active_brightness if initial_busy else inactive_brightness
        initial_status = f"busy ({config['active_color']})" if initial_busy else f"available ({config['inactive_color']})"

    print(f"Initializing {len(selected_devices)} device(s)...")
    for device in selected_devices:
        print(f"  Setting up {device.sku}@{device.ip}...")
        await _apply_color_to_device(controller, device, initial_rgb, initial_brightness)
        print(f"    ✓ Set to {initial_status} (RGB: {initial_rgb}, brightness: {initial_brightness})")

    last_busy: bool | None = is_recording() if not get_mode_rgb else None
    if on_status_change is not None and not get_mode_rgb:
        on_status_change(bool(last_busy))
    if get_mode_rgb and last_busy is None:
        last_busy = is_recording()

    try:
        while True:
            if get_mode_rgb:
                mode, m_rgb, a_rgb, inactive_rgb, a_br, i_br, m_br = get_mode_rgb()
                active_rgb = a_rgb
                a_br, i_br, m_br = max(0, min(100, a_br)), max(0, min(100, i_br)), max(0, min(100, m_br))
                if mode == "off":
                    for device in selected_devices:
                        await _apply_color_to_device(controller, device, inactive_rgb, 0)
                    await asyncio.sleep(1.0)
                    continue
                if mode == "manual" and m_rgb is not None:
                    rgb, br = m_rgb, m_br
                    for device in selected_devices:
                        await _apply_color_to_device(controller, device, rgb, br)
                    await asyncio.sleep(1.0)
                    continue
                busy = is_recording()
                if on_status_change is not None:
                    on_status_change(busy)
                rgb = active_rgb if busy else inactive_rgb
                br = a_br if busy else i_br
                for device in selected_devices:
                    await _apply_color_to_device(controller, device, rgb, br)
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            busy = is_recording()
            if on_status_change is not None:
                on_status_change(busy)
            if busy != last_busy:
                rgb = active_rgb if busy else inactive_rgb
                br = active_brightness if busy else inactive_brightness
                status = f"busy ({config['active_color']})" if busy else f"available ({config['inactive_color']})"
                print(f"Status changed to: {status} (RGB: {rgb}, brightness: {br})")
                for device in selected_devices:
                    await _apply_color_to_device(controller, device, rgb, br)
                    print(f"  → Updated {device.sku}@{device.ip}")
                print(status)
                last_busy = busy
            await asyncio.sleep(CHECK_INTERVAL)
    except asyncio.CancelledError:
        pass
    finally:
        controller.cleanup()
        print("\nStopped.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Busylights: update Govee light(s) by meeting status (mic in use)."
    )
    parser.add_argument(
        "-d",
        "--discover",
        action="store_true",
        help="Scan for nearby Govee devices and list them, then exit.",
    )
    parser.add_argument(
        "-c",
        "--config",
        action="store_true",
        help="Choose which light to use (interactive); save selection for future runs.",
    )
    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if args.discover:
        loop.run_until_complete(run_discover())
        loop.close()
        return

    if args.config:
        ok = loop.run_until_complete(choose_device())
        loop.close()
        sys.exit(0 if ok else 1)

    task = loop.create_task(run_loop())

    def stop() -> None:
        task.cancel()

    try:
        loop.add_signal_handler(signal.SIGINT, stop)
        loop.add_signal_handler(signal.SIGTERM, stop)
    except (ValueError, OSError):
        pass  # signal handlers not supported on this platform

    try:
        ok = loop.run_until_complete(task)
        if ok is False:
            sys.exit(1)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
