#!/usr/bin/env python3
import curses
import subprocess

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    stdscr.keypad(True)
    values = [0, 0, 0]
    labels = ["HH", "MM", "SS"]
    limits = [99, 59, 59]
    selected = 1
    
    def draw():
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        if h < 10 or w < 35:
            stdscr.addstr(0, 0, f"Terminal too small! ({w}x{h}) Need 50x12")
            stdscr.refresh()
            return
        try:
            title = "SET TIMER"
            stdscr.addstr(h//2 - 4, w//2 - len(title)//2, title, curses.color_pair(3) | curses.A_BOLD)
            x_start = w//2 - 10
            y = h//2 - 1
            for i, (val, label) in enumerate(zip(values, labels)):
                segment = f" {val:02d} "
                x = x_start + i * 7
                if i == selected:
                    stdscr.addstr(y, x, segment, curses.color_pair(2) | curses.A_BOLD | curses.A_REVERSE)
                else:
                    stdscr.addstr(y, x, segment, curses.color_pair(1) | curses.A_BOLD)
                if i < 2:
                    stdscr.addstr(y, x + 4, " : ", curses.color_pair(1))
            for i, label in enumerate(labels):
                x = x_start + i * 7 + 1
                stdscr.addstr(y + 1, x, label, curses.color_pair(2) if i == selected else curses.color_pair(3))
            hints = "up/down adjust   left/right switch   Enter start   Esc cancel"
            stdscr.addstr(h//2 + 3, w//2 - len(hints)//2, hints, curses.color_pair(3))
        except curses.error:
            pass
        stdscr.refresh()
        
    while True:
        draw()
        key = stdscr.getch()
        if key == curses.KEY_UP:
            values[selected] = (values[selected] + 1) % (limits[selected] + 1)
        elif key == curses.KEY_DOWN:
            values[selected] = (values[selected] - 1) % (limits[selected] + 1)
        elif key == curses.KEY_RIGHT:
            selected = (selected + 1) % 3
        elif key == curses.KEY_LEFT:
            selected = (selected - 1) % 3
        elif key in (10, 13):
            total = values[0] * 3600 + values[1] * 60 + values[2]
            if total > 0:
                return str(total)
        elif key == 27:
            return None

result = curses.wrapper(main)
if result:
    subprocess.Popen(["swaymsg", "exec", 
        f"kitty --class StickyTimer --override font_size=30 -e termdown {result}"])
