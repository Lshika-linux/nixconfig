#!/usr/bin/env python3
import curses
import subprocess
import os
import glob

def get_apps():
    apps = {}
    dirs = [
        "/run/current-system/sw/share/applications",
        os.path.expanduser("~/.nix-profile/share/applications"),
        "/etc/profiles/per-user/rafi/share/applications",
    ]
    for d in dirs:
        for path in glob.glob(f"{d}/*.desktop"):
            name = None
            exec_cmd = None
            nodisplay = False
            try:
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Name=") and name is None:
                            name = line[5:]
                        elif line.startswith("Exec=") and exec_cmd is None:
                            exec_cmd = line[5:]
                        elif line == "NoDisplay=true":
                            nodisplay = True
            except:
                continue
            if name and exec_cmd and not nodisplay:
                # clean exec args like %u %f %U
                exec_cmd = " ".join(p for p in exec_cmd.split() if not p.startswith("%"))
                apps[name] = exec_cmd
    return dict(sorted(apps.items(), key=lambda x: x[0].lower()))

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    stdscr.keypad(True)

    all_apps = get_apps()
    query = ""
    selected = 0

    def filtered():
        q = query.lower()
        return [(n, c) for n, c in all_apps.items() if q in n.lower()]

    def draw():
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        title = "APP LAUNCHER"
        try:
            stdscr.addstr(0, w//2 - len(title)//2, title, curses.color_pair(2) | curses.A_BOLD)
        except curses.error:
            pass

        # search bar
        search_label = f" > {query}_"
        try:
            stdscr.addstr(1, 0, search_label.ljust(w - 1), curses.color_pair(4))
        except curses.error:
            pass

        apps = filtered()
        max_rows = h - 4
        start = max(0, selected - max_rows // 2)
        end = min(len(apps), start + max_rows)

        for i, (name, _) in enumerate(apps[start:end], start=start):
            row = i - start + 3
            if row >= h - 1:
                break
            try:
                if i == selected:
                    stdscr.addstr(row, 0, f" {name}".ljust(w - 1), curses.color_pair(3) | curses.A_BOLD)
                else:
                    stdscr.addstr(row, 0, f" {name}", curses.color_pair(1))
            except curses.error:
                pass

        stdscr.refresh()

    while True:
        draw()
        key = stdscr.getch()

        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            apps = filtered()
            selected = min(len(apps) - 1, selected + 1)
        elif key in (10, 13):
            apps = filtered()
            if apps:
                return apps[selected][1]
            return None
        elif key == 27:
            return None
        elif key in (curses.KEY_BACKSPACE, 127):
            query = query[:-1]
            selected = 0
        elif 32 <= key <= 126:
            query += chr(key)
            selected = 0

result = curses.wrapper(main)
if result:
    subprocess.Popen(["swaymsg", "exec", result])
