#!/usr/bin/env python3
"""
cockpit_photographer.py — background daemon, co fotí náhledy CELÝCH workspaců
(ne jednotlivých oken - dashboard teď přepíná po workspace, ne po appce).

Klíčová věc, díky které tohle vůbec jde snadno: grim (wlr-screencopy) umí
vyfotit jen to, co se aktuálně reálně vykresluje na obrazovku. Neviditelný
workspace se vyfotit nedá - proto se fotí "opportunisticky" při
workspace::focus (přesně ten moment, kdy je celý workspace vidět vcelku),
a cache pak dashboardu stačí i pro workspace, co zrovna vidět není.

Fotí se přes `grim -o <output>` (celý fyzický monitor - CELÝCH 1920x1080,
s barem se vším), NE `grim -g <workspace rect>`. Bar (waybar/swaybar) je
layer-shell surface připnutá k výstupu, ne součást workspace stromu - proto
je output capture jediný způsob, jak ho dostat do screenshotu. Output, na
kterém workspace N zrovna leží, se dohledá čerstvým get_tree() (ne z dat
eventu - ta nesou jen podstrom "current" workspace bez napojení na
strom/parent, takže z nich se k output nelze prolézt).

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


def find_workspace_and_output(i3, ws_num):
    """Čerstvý get_tree(), projde outputy -> jejich workspace děti -> najde
    ws_num a vrátí (workspace_node, output_name). Musí to být čerstvý strom
    (ne data z eventu), protože jen tak má Con navázaný .parent řetězec
    až k output uzlu."""
    try:
        tree = i3.get_tree()
    except Exception:
        return None, None
    for output in tree.nodes:
        if output.type != "output":
            continue
        for ws in output.nodes:
            if ws.type == "workspace" and ws.num == ws_num:
                return ws, output.name
    return None, None


def workspace_has_cockpit_window(ws_node):
    """Je na tomhle workspace PRÁVĚ TEĎ nějaké cockpit okno? Pokud ano, nefoť
    (jinak vznikne rekurzivní screenshot - dashboard fotící sám sebe)."""
    if ws_node is None:
        return False
    try:
        return any((leaf.app_id or "") in COCKPIT_APP_IDS for leaf in ws_node.leaves())
    except Exception:
        return False


def take_screenshot(ws_num, output_name):
    if ws_num is None or not output_name:
        return
    path = os.path.join(CACHE_DIR, f"ws_{ws_num}.png")
    tmp_path = os.path.join(CACHE_DIR, f"ws_{ws_num}_tmp.png")

    try:
        r = subprocess.run(
            ["grim", "-o", output_name, tmp_path],
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
    """ws je i3ipc WorkspaceReply/Con - potřebuje jen .num, output se
    dohledává čerstvě uvnitř do() (viz find_workspace_and_output)."""
    if ws is None:
        return
    num = ws.num

    def do():
        time.sleep(delay)
        try:
            ws_node, output_name = find_workspace_and_output(i3, num)
            if not output_name:
                return
            if workspace_has_cockpit_window(ws_node):
                return  # dashboard/widget je zrovna na tomhle workspace - nefoť sám sebe
            take_screenshot(num, output_name)
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
