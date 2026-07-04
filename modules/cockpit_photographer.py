#!/usr/bin/env python3
"""
cockpit_photographer.py — background daemon, co fotí náhledy oken.

Wayland/Sway adaptace tvého i3_photographer.py. Místo xwd/maim (X11)
používá grim (wlr-screencopy) a capturuje podle geometrie okna ze sway
stromu. Nativní Wayland okna nemají X11 window id, takže cache klíčujeme
podle sway con_id — funguje jednotně pro Wayland i XWayland okna.

Poslouchá i3ipc eventy (Sway je i3-ipc kompatibilní, i3ipc-python
funguje beze změny):
  - window::focus    -> vyfoť okno, co právě dostalo fokus
  - window::new      -> vyfoť nové okno (delší delay, ať se stihne vykreslit)
  - workspace::focus -> vyfoť všechna okna na nově viditelném workspace
  - window::close    -> smaž cache náhled zavřeného okna

Cache: ~/.cache/cockpit/thumbs/<con_id>.png (atomický zápis přes os.replace)
"""
import i3ipc
import subprocess
import threading
import os
import time

CACHE_DIR = os.path.expanduser("~/.cache/cockpit/thumbs")
os.makedirs(CACHE_DIR, exist_ok=True)


def take_screenshot(con_id, x, y, w, h):
    if not con_id or w <= 0 or h <= 0:
        return
    path = os.path.join(CACHE_DIR, f"{con_id}.png")
    tmp_path = os.path.join(CACHE_DIR, f"{con_id}_tmp.png")
    geometry = f"{x},{y} {w}x{h}"

    try:
        r = subprocess.run(
            ["grim", "-g", geometry, tmp_path],
            timeout=5, capture_output=True
        )
        if r.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            # zmenšit, ať cache nenabobtná - dashboard stejně kreslí malé thumbnaily
            subprocess.run(
                ["convert", tmp_path, "-resize", "480x>", tmp_path],
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


def shoot_window(i3, con_id, delay=0.3):
    def do():
        time.sleep(delay)
        try:
            node = i3.get_tree().find_by_id(con_id)
            if node and node.rect:
                take_screenshot(con_id, node.rect.x, node.rect.y,
                                 node.rect.width, node.rect.height)
        except Exception as e:
            print(f"[cockpit_photographer] chyba u con_id {con_id}: {e}")

    threading.Thread(target=do, daemon=True).start()


def is_real_window(node):
    """True pro skutečné okno (Wayland i XWayland), ne pro workspace/output/scratchpad."""
    return node.type in ("con", "floating_con") and (node.app_id or node.window)


def cleanup_thumb(con_id):
    path = os.path.join(CACHE_DIR, f"{con_id}.png")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def start_photographer():
    i3 = i3ipc.Connection()

    def on_window_focus(i3, e):
        if is_real_window(e.container):
            shoot_window(i3, e.container.id, delay=0.15)

    def on_workspace_focus(i3, e):
        for leaf in e.current.leaves():
            if is_real_window(leaf):
                shoot_window(i3, leaf.id, delay=0.1)

    def on_window_new(i3, e):
        if is_real_window(e.container):
            shoot_window(i3, e.container.id, delay=1.2)

    def on_window_close(i3, e):
        if is_real_window(e.container):
            cleanup_thumb(e.container.id)

    i3.on('window::focus', on_window_focus)
    i3.on('workspace::focus', on_workspace_focus)
    i3.on('window::new', on_window_new)
    i3.on('window::close', on_window_close)

    # prvotní scan při startu
    for leaf in i3.get_tree().leaves():
        if is_real_window(leaf):
            shoot_window(i3, leaf.id, delay=0.1)

    i3.main()


if __name__ == "__main__":
    start_photographer()
