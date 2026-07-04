#!/usr/bin/env python3
"""
cockpit_client.py — toggle všech cockpit widgetů najednou (Mod4+grave).

První stisk otevře všech 7 widgetů. Druhý stisk (pokud je aspoň jeden
z nich otevřený) je všechny zavře. Widgety zůstávají oddělené procesy/okna,
přesně stejné jako při jednotlivých keybindech (Mod4+c, Mod4+p, ...) —
tohle jen spouští/zavírá všech 7 naráz.
Data pro weather/wifi/bt jdou z cockpit_daemon.py, takže i souběžné
otevření je prakticky okamžité.
"""
import subprocess
import json
import os

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, "scripts_sway")

APP_IDS = [
    "WindowSwitcher",
    "Connectivity",
    "Weather",
    "TimerPicker",
    "Calendar",
    "PowerMenu",
    "AppLauncher",
]

WIDGETS = [
    ["kitty", "-o", "resize_in_steps=no", "--class", "WindowSwitcher", "-e", "python3", f"{SCRIPTS}/switcher.py"],
    ["kitty", "-o", "resize_in_steps=no", "--class", "Connectivity", "-e", "python3", f"{SCRIPTS}/connectivity.py"],
    ["kitty", "-o", "resize_in_steps=no", "--class", "Weather", "-e", "python3", f"{SCRIPTS}/weather.py"],
    ["kitty", "-o", "resize_in_steps=no", "--class", "TimerPicker", "--override", "font_size=14", "-e", "python3", f"{SCRIPTS}/timer.py"],
    ["kitty", "-o", "resize_in_steps=no", "--class", "Calendar", "-e", "python3", f"{SCRIPTS}/raficalendar.py"],
    ["kitty", "-o", "resize_in_steps=no", "--class", "PowerMenu", "-e", "python3", f"{SCRIPTS}/powermenu.py"],
    ["kitty", "-o", "resize_in_steps=no", "--class", "AppLauncher", "-e", "python3", f"{SCRIPTS}/launcher.py"],
]

def get_open_app_ids():
    """Vrátí set app_id, které jsou aktuálně otevřené podle sway stromu."""
    try:
        r = subprocess.run(
            ["swaymsg", "-t", "get_tree"],
            capture_output=True, text=True, timeout=2
        )
        tree = json.loads(r.stdout)
    except Exception:
        return set()

    found = set()

    def walk(node):
        app_id = node.get("app_id")
        if app_id:
            found.add(app_id)
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child)

    walk(tree)
    return found


def close_all():
    for app_id in APP_IDS:
        subprocess.run(
            ["swaymsg", f'[app_id="{app_id}"] kill'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def open_all():
    for cmd in WIDGETS:
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main():
    open_now = get_open_app_ids()
    if open_now & set(APP_IDS):
        close_all()
    else:
        open_all()


if __name__ == "__main__":
    main()
