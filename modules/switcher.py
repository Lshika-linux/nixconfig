#!/usr/bin/env python3
import curses
import subprocess
import json

BLACKLIST_NAMES = ["switcher.py", "timer.py"]

def get_windows():
    raw = subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True, text=True).stdout
    tree = json.loads(raw)
    windows = []

    def walk(node, current_ws=None):
        if node.get("type") == "workspace":
            current_ws = node.get("name", "?")
        if node.get("type") in ("con", "floating_con") and node.get("app_id") is not None and node.get("name"):
            name = node["name"]
            if not any(b in name for b in BLACKLIST_NAMES):
                windows.append({
                    "id": node["id"],
                    "name": name,
                    "app": node.get("app_id") or "?",
                    "focused": node.get("focused", False),
                    "ws": current_ws or "?",
                })
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child, current_ws)

    walk(tree)
    return windows

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(5, curses.COLOR_GREEN, -1)
    stdscr.keypad(True)

    windows = [w for w in get_windows() if "python3" not in w["name"]]
    if not windows:
        return None
    
    selected = next((i for i, w in enumerate(windows) if w["focused"]), 0)

    def draw():
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        if h < 5 or w < 30:
            stdscr.addstr(0, 0, "Too small!")
            stdscr.refresh()
            return

        title = "WINDOW SWITCHER"
        try:
            stdscr.addstr(0, w//2 - len(title)//2, title, curses.color_pair(3) | curses.A_BOLD)
        except curses.error:
            pass

        max_rows = h - 4
        start = max(0, selected - max_rows // 2)
        end = min(len(windows), start + max_rows)

        for i, win in enumerate(windows[start:end], start=start):
            row = i - start + 2
            if row >= h - 2:
                break

            ws_str = f"[{win['ws']}]"
            app_str = win["app"][:12].ljust(12)
            name_str = win["name"][:w - 20 - len(ws_str)]
            line = f" {ws_str} {app_str}  {name_str}"

            try:
                if i == selected:
                    stdscr.addstr(row, 0, line.ljust(w - 1), curses.color_pair(4) | curses.A_BOLD)
                elif win["focused"]:
                    stdscr.addstr(row, 0, line, curses.color_pair(5))
                else:
                    stdscr.addstr(row, 0, line, curses.color_pair(1))
            except curses.error:
                pass

        hints = "↑↓ navigate   Enter focus   Esc cancel"
        try:
            stdscr.addstr(h - 1, w//2 - len(hints)//2, hints, curses.color_pair(3))
        except curses.error:
            pass

        stdscr.refresh()

    while True:
        draw()
        key = stdscr.getch()
        if key == curses.KEY_UP:
            selected = (selected - 1) % len(windows)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(windows)
        elif key == ord('\t'):
            selected = (selected + 1) % len(windows)
        elif key in (10, 13):
            return windows[selected]["id"]
        elif key == 27:
            return None

result = curses.wrapper(main)
if result:
    subprocess.run(["swaymsg", f"[con_id={result}]", "focus"])
