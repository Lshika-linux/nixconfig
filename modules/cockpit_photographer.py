#!/usr/bin/env python3
"""
cockpit_photographer.py — background daemon, co fotí náhledy CELÝCH workspaců
(ne jednotlivých oken - dashboard teď přepíná po workspace, ne po appce).

Klíčová věc, díky které tohle vůbec jde snadno: grim (wlr-screencopy) umí
vyfotit jen to, co se aktuálně reálně vykresluje na obrazovku. Neviditelný
workspace se vyfotit nedá - proto se fotí "opportunisticky" při
workspace::focus (přesně ten moment, kdy je celý workspace vidět vcelku),
a cache pak dashboardu stačí i pro workspace, co zrovna vidět není.

Poslouchá i3ipc eventy (Sway je i3-ipc kompatibilní):
  - workspace::focus -> vyfoť nově viditelný workspace celý, jedním grim
  - window::new/close/move -> přefoť AKTUÁLNĚ FOCUSNUTÝ workspace (jen ten
    může být viditelný, takže jen ten stojí za refresh)

Cache: ~/.cache/cockpit/thumbs/ws_<num>.png (atomický zápis přes os.replace)
"""
import i3ipc
import subprocess
import threading
import os
import time

CACHE_DIR = os.path.expanduser("~/.cache/cockpit/thumbs")
os.makedirs(CACHE_DIR, exist_ok=True)

# app_id/class, pod kterým běží dashboard a ostatní cockpit widgety - žádné
# z nich se nesmí nikdy vyfotit jako "obsah workspace", jinak vznikne
# rekurzivní screenshot (dashboard fotící sám sebe) a cache pro ten
# workspace zůstane "otrávená" dokud ji nepřepíše něco jiného.
# POZOR: over si přesný název přes `swaymsg -t get_tree | grep app_id`
# s dashboardem otevřeným - jestli launcher/kitty config používá jiný
# --class než "CockpitDashboard", uprav tenhle set.
COCKPIT_APP_IDS = {
    "CockpitDashboard", "WindowSwitcher", "Connectivity", "Weather",
    "TimerPicker", "StickyTimer", "Calendar", "PowerMenu", "AppLauncher",
    "FloatingCenter",
}


def workspace_has_cockpit_window(i3, ws_num):
    """Fresh dotaz na strom (ne stará event data) - je na workspace ws_num
    PRÁVĚ TEĎ nějaké cockpit okno? Pokud ano, nefoť."""
    try:
        ws_node = next((w for w in i3.get_tree().workspaces() if w.num == ws_num), None)
        if not ws_node:
            return False
        return any((leaf.app_id or "") in COCKPIT_APP_IDS for leaf in ws_node.leaves())
    except Exception:
        return False


def take_screenshot(ws_num, x, y, w, h):
    if ws_num is None or w <= 0 or h <= 0:
        return
    path = os.path.join(CACHE_DIR, f"ws_{ws_num}.png")
    tmp_path = os.path.join(CACHE_DIR, f"ws_{ws_num}_tmp.png")
    geometry = f"{x},{y} {w}x{h}"

    try:
        r = subprocess.run(
            ["grim", "-g", geometry, tmp_path],
            timeout=5, capture_output=True
        )
        if r.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            # 960px - dost detailu i když dashboard ukáže náhled skoro na
            # celou obrazovku, bez zbytečně velké cache.
            subprocess.run(
                ["convert", tmp_path, "-resize", "960x>", tmp_path],
                timeout=10, capture_output=True
            )
            os.replace(tmp_path, path)
    except Exception:
        pass
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def shoot_workspace(i3, ws, delay=0.15):
    """ws je i3ipc WorkspaceReply/Con - potřebuje .num a .rect."""
    if ws is None:
        return
    num, rect = ws.num, ws.rect

    def do():
        time.sleep(delay)
        try:
            if workspace_has_cockpit_window(i3, num):
                return  # dashboard/widget je zrovna na tomhle workspace - nefoť sám sebe
            take_screenshot(num, rect.x, rect.y, rect.width, rect.height)
        except Exception as e:
            print(f"[cockpit_photographer] chyba u workspace {num}: {e}")

    threading.Thread(target=do, daemon=True).start()


def get_focused_workspace(i3):
    focused = i3.get_tree().find_focused()
    return focused.workspace() if focused else None


def start_photographer():
    i3 = i3ipc.Connection()

    def on_workspace_focus(i3, e):
        shoot_workspace(i3, e.current, delay=0.1)

    def on_window_change(i3, e):
        # jen aktuálně viditelný workspace stojí za refresh - neviditelný
        # se stejně nedá vyfotit, dokud se na něj nepřepne (viz workspace::focus)
        shoot_workspace(i3, get_focused_workspace(i3), delay=0.3)

    i3.on('workspace::focus', on_workspace_focus)
    i3.on('window::new', on_window_change)
    i3.on('window::close', on_window_change)
    i3.on('window::move', on_window_change)

    # prvotní scan při startu - vyfoť aspoň ten, co je zrovna vidět
    shoot_workspace(i3, get_focused_workspace(i3), delay=0.1)

    i3.main()


if __name__ == "__main__":
    start_photographer()
