#!/usr/bin/env python3
import curses
import subprocess

from cockpit_common import query_daemon

def get_wifi_info():
    cached = query_daemon("wifi")
    if cached is not None:
        return cached

    try:
        r = subprocess.run(["iwctl", "station", "wlan0", "show"],
                          capture_output=True, text=True)
        ssid = None
        rssi = None
        for line in r.stdout.split("\n"):
            if "Connected network" in line:
                ssid = line.split()[-1]
            if "AverageRSSI" in line:
                rssi = line.split()[-2]
        if ssid:
            return {"ssid": ssid, "rssi": rssi}
    except:
        pass
    return None


def get_bt_info():
    cached = query_daemon("bt")
    if cached is not None:
        return cached

    try:
        r = subprocess.run(["bluetoothctl", "devices", "Paired"],
                          capture_output=True, text=True)
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            mac = parts[1]
            name = parts[2]
            info = subprocess.run(["bluetoothctl", "info", mac],
                                 capture_output=True, text=True)
            connected = "Connected: yes" in info.stdout
            battery = None
            for l in info.stdout.split("\n"):
                if "Battery Percentage" in l:
                    try:
                        battery = l.split("(")[1].split(")")[0] + "%"
                    except:
                        pass
            if connected:
                return {"name": name, "battery": battery}
    except:
        pass
    return None

def draw_box(stdscr, y, x, h, w, focused, title):
    color = curses.color_pair(3) if focused else curses.color_pair(6)
    try:
        stdscr.addch(y, x, curses.ACS_ULCORNER, color)
        stdscr.addch(y, x + w - 1, curses.ACS_URCORNER, color)
        stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER, color)
        stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER, color)
        for i in range(1, w - 1):
            stdscr.addch(y, x + i, curses.ACS_HLINE, color)
            stdscr.addch(y + h - 1, x + i, curses.ACS_HLINE, color)
        for i in range(1, h - 1):
            stdscr.addch(y + i, x, curses.ACS_VLINE, color)
            stdscr.addch(y + i, x + w - 1, curses.ACS_VLINE, color)
        stdscr.addstr(y, x + 2, f" {title} ", color | curses.A_BOLD)
    except curses.error:
        pass

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_WHITE, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_RED, -1)
    curses.init_pair(6, curses.COLOR_BLACK+8, -1)
    stdscr.keypad(True)

    focus = 0
    wifi = get_wifi_info()
    bt = get_bt_info()

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        half = w // 2
        box_h = h - 2
        mid_row = box_h // 2 - 1

        draw_box(stdscr, 0, 0, box_h, half, focus == 0, "󰖩  WiFi")
        draw_box(stdscr, 0, half, box_h, half, focus == 1, "󰂯  Bluetooth")
        
        # WiFi content
        if wifi:
            ssid = wifi['ssid']
            rssi = f"{wifi['rssi']} dBm"
            try:
                stdscr.addstr(mid_row, half//2 - len(ssid)//2, ssid,
                             curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(mid_row + 1, half//2 - len(rssi)//2, rssi,
                             curses.color_pair(1))
            except curses.error:
                pass
        else:
            msg = "disconnected"
            try:
                stdscr.addstr(mid_row, half//2 - len(msg)//2, msg, curses.color_pair(5))
            except curses.error:
                pass

        # BT content
        if bt:
            name = bt['name']
            bat = f"bat: {bt['battery']}" if bt['battery'] else "connected"
            try:
                stdscr.addstr(mid_row, half + half//2 - len(name)//2, name,
                             curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(mid_row + 1, half + half//2 - len(bat)//2, bat,
                             curses.color_pair(1))
            except curses.error:
                pass
        else:
            msg = "disconnected"
            try:
                stdscr.addstr(mid_row, half + half//2 - len(msg)//2, msg,
                             curses.color_pair(5))
            except curses.error:
                pass

        # Bottom hints
        hints = "TAB switch   ENTER open   ESC close"
        try:
            stdscr.addstr(h - 1, w//2 - len(hints)//2, hints, curses.color_pair(2))
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()

        if key == 27:
            return
        elif key == ord('\t'):
            focus = 1 - focus
        elif key in (10, 13):
            if focus == 0:
                subprocess.Popen(["swaymsg", "exec", "kitty --class FloatingCenter -e impala"])
            else:
                subprocess.Popen(["swaymsg", "exec", "kitty --class FloatingCenter -e bluetuith"])
            return

curses.wrapper(main)
