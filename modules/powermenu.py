#!/usr/bin/env python3
import curses
import subprocess
import os

OPTIONS = [
    ("  Lock",     ["bash", os.path.expanduser("~/scripts_sway/lock.sh")]),
    ("  Sleep",    ["systemctl", "suspend"]),
    ("  Logout",   ["swaymsg", "exit"]),
    ("  Reboot",   ["systemctl", "reboot"]),
    ("  Shutdown", ["systemctl", "poweroff"]),
]

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(4, curses.COLOR_RED, -1)
    stdscr.keypad(True)

    selected = 0

    def draw():
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        title = "POWER MENU"
        try:
            stdscr.addstr(0, w//2 - len(title)//2, title, curses.color_pair(2) | curses.A_BOLD)
        except curses.error:
            pass

        for i, (label, _) in enumerate(OPTIONS):
            row = i + 2
            danger = label.strip() in ["  Shutdown", "  Reboot", "  Logout"]
            try:
                if i == selected:
                    stdscr.addstr(row, 0, label.ljust(w - 1), curses.color_pair(3) | curses.A_BOLD)
                elif danger:
                    stdscr.addstr(row, 0, label, curses.color_pair(4))
                else:
                    stdscr.addstr(row, 0, label, curses.color_pair(1))
            except curses.error:
                pass

        hints = "↑↓ navigate   Enter confirm   Esc cancel"
        try:
            stdscr.addstr(h - 1, w//2 - len(hints)//2, hints, curses.color_pair(2))
        except curses.error:
            pass

        stdscr.refresh()

    while True:
        draw()
        key = stdscr.getch()
        if key == curses.KEY_UP:
            selected = (selected - 1) % len(OPTIONS)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(OPTIONS)
        elif key in (10, 13):
            return OPTIONS[selected][1]
        elif key == 27:
            return None

result = curses.wrapper(main)
if result:
    subprocess.run(result)
