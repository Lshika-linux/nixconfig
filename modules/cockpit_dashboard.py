#!/usr/bin/env python3
"""
cockpit_dashboard.py — fullscreen dashboard (Win+grave).

Levý sloupec (1/5): AppLauncher (úplně nahoře) -> běžící appky (app_id) ->
Weather / Calendar / Timer / Connectivity -> pinnuté PowerMenu dole.
Fokus při startu naskočí na první appku (AppLauncher je jen o Shift+Tab výš).

Pravá plocha (4/5): kontextový obsah podle vybrané položky - grid oken,
plné počasí, kalendář s poznámkami, timer picker, connectivity chooser.

Connectivity je jediná věc, co NEJDE vykreslit v curses - impala/bluetuith
jsou vlastní interaktivní TUI. Řeší se přes kitty remote control: dashboard
běží v kitty s --listen-on, a při volbě WiFi/BT se vedle spustí OPRAVDOVÝ
druhý kitty panel (kitty @ launch --location=vsplit) se skutečným impala/
bluetuith procesem. Žádná emulace terminálu, je to nativní kitty split.

PowerMenu jde spustit odkudkoliv v dashboardu klávesou (l/s/o/r/p), navíc
je i součástí Tab cyklení jako pinnuté položky dole v levém sloupci.
"""
import curses
import subprocess
import json
import os
import calendar
import datetime

from cockpit_common import query_daemon

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, "scripts_sway")
NOTES_FILE = os.path.expanduser("~/.local/share/calendar_notes.json")
KITTY_SOCKET = "/tmp/cockpit-dashboard.sock"

EXCLUDE_APP_IDS = {
    "WindowSwitcher", "Connectivity", "Weather", "TimerPicker", "StickyTimer",
    "Calendar", "PowerMenu", "AppLauncher", "FloatingCenter", "CockpitDashboard",
}

DESKTOP_DIRS = [
    "/run/current-system/sw/share/applications",
    os.path.expanduser("~/.nix-profile/share/applications"),
    os.path.expanduser("~/.local/state/nix/profile/share/applications"),
    os.path.expanduser("~/.local/share/applications"),
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/etc/profiles/per-user/" + os.environ.get("USER", "") + "/share/applications",
    "/nix/var/nix/profiles/default/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/usr/share/applications",
]

POWER_OPTIONS = [
    ("l", "Lock", ["bash", os.path.join(SCRIPTS, "lock.sh")]),
    ("s", "Sleep", ["systemctl", "suspend"]),
    ("o", "Logout", ["swaymsg", "exit"]),
    ("r", "Reboot", ["systemctl", "reboot"]),
    ("p", "Shutdown", ["systemctl", "poweroff"]),
]


# ---------- weather (z weather.py) ----------

def weather_icon(desc):
    desc = desc.lower()
    if "thunder" in desc: return "⚡"
    if "snow" in desc: return "❄"
    if "rain" in desc or "drizzle" in desc: return "🌧"
    if "cloud" in desc or "overcast" in desc: return "☁"
    if "fog" in desc or "mist" in desc: return "🌫"
    if "sunny" in desc or "clear" in desc: return "☀"
    if "partly" in desc: return "⛅"
    return "~"


# ---------- sway tree / running apps ----------

def get_running_apps():
    try:
        r = subprocess.run(["swaymsg", "-t", "get_tree"],
                            capture_output=True, text=True, timeout=2)
        tree = json.loads(r.stdout)
    except Exception:
        return {}

    groups = {}

    def walk(node):
        app_id = node.get("app_id")
        wp = node.get("window_properties") or {}
        name = app_id or wp.get("class")
        if name and name not in EXCLUDE_APP_IDS and node.get("type") in ("con", "floating_con"):
            groups.setdefault(name, []).append({
                "con_id": node.get("id"),
                "title": node.get("name") or name,
                "rect": node.get("rect", {}),
            })
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child)

    walk(tree)
    return groups


def grid_layout(n):
    if n <= 0:
        return []
    if n <= 3:
        return [n]
    rows = -(-n // 3)
    base = n // rows
    extra = n % rows
    return [base + 1 if i < extra else base for i in range(rows)]


def focus_window(con_id):
    subprocess.run(["swaymsg", f"[con_id={con_id}] focus"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------- calendar (z raficalendar.py) ----------

def load_notes():
    try:
        with open(NOTES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_notes(notes):
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f)


def note_key(year, month, day):
    return f"{year}-{month:02d}-{day:02d}"


# ---------- app launcher (generický scan .desktop souborů) ----------

def scan_desktop_apps():
    apps = []
    seen = set()
    for d in DESKTOP_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except Exception:
            continue
        for fname in entries:
            if not fname.endswith(".desktop") or fname in seen:
                continue
            seen.add(fname)
            name = None
            exec_cmd = None
            no_display = False
            try:
                with open(os.path.join(d, fname), errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Name=") and name is None:
                            name = line[5:]
                        elif line.startswith("Exec=") and exec_cmd is None:
                            exec_cmd = line[5:]
                        elif line.startswith("NoDisplay=true"):
                            no_display = True
            except Exception:
                continue
            if name and exec_cmd and not no_display:
                clean = " ".join(p for p in exec_cmd.split() if not p.startswith("%"))
                apps.append((name, clean))
    apps.sort(key=lambda a: a[0].lower())
    return apps


# ---------- drawing helpers ----------

def draw_box(stdscr, y, x, h, w, focused, title=""):
    if h < 2 or w < 2:
        return
    color = curses.color_pair(3) | curses.A_BOLD if focused else curses.color_pair(6)
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
        if title:
            stdscr.addstr(y, x + 2, f" {title[:w - 4]} ", color)
    except curses.error:
        pass


def safe_addstr(stdscr, y, x, text, attr=0):
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


# ---------- pravý panel: grid oken ----------

def draw_grid(stdscr, windows, selected, y0, x0, width, height):
    rows = grid_layout(len(windows))
    if not rows:
        safe_addstr(stdscr, y0 + height // 2, x0 + width // 2 - 5, "no windows", curses.color_pair(5))
        return
    cell_h = height // len(rows)
    idx = 0
    y = y0
    for row_count in rows:
        cell_w = width // row_count
        x = x0
        for _ in range(row_count):
            win = windows[idx]
            draw_box(stdscr, y, x, cell_h, cell_w, idx == selected, win["title"])
            dims = f"{win['rect'].get('width', '?')}x{win['rect'].get('height', '?')}"
            safe_addstr(stdscr, y + cell_h // 2, x + cell_w // 2 - len(dims) // 2, dims, curses.color_pair(6))
            idx += 1
            x += cell_w
        y += cell_h


# ---------- pravý panel: weather ----------

def draw_weather(stdscr, y0, x0, width, height):
    data = query_daemon("weather")
    if not data:
        safe_addstr(stdscr, y0 + height // 2, x0 + width // 2 - 4, "no data", curses.color_pair(5))
        return

    row = y0
    safe_addstr(stdscr, row, x0 + width // 2 - len(data["city"]) // 2, data["city"],
                curses.color_pair(2) | curses.A_BOLD)
    row += 2

    icon = weather_icon(data["desc"])
    temp_str = f"{icon}  {data['temp']}°C"
    safe_addstr(stdscr, row, x0 + width // 2 - len(temp_str) // 2, temp_str,
                curses.color_pair(3) | curses.A_BOLD)
    row += 1

    desc_str = data["desc"]
    feels_str = f"feels {data['feels']}°C   wind {data['wind']} km/h   humidity {data['humidity']}%"
    safe_addstr(stdscr, row, x0 + width // 2 - len(desc_str) // 2, desc_str, curses.color_pair(1))
    row += 1
    safe_addstr(stdscr, row, x0 + width // 2 - len(feels_str) // 2, feels_str, curses.color_pair(6))
    row += 2

    if data.get("forecast"):
        col_w = width // 3
        for i, day in enumerate(data["forecast"]):
            x = x0 + i * col_w
            icon_f = weather_icon(day["desc"])
            date_parts = day["date"].split("-")
            date_short = f"{date_parts[2]}.{date_parts[1]}"
            temp_range = f"{day['min']}-{day['max']}°C"
            safe_addstr(stdscr, row, x, date_short.center(col_w - 1), curses.color_pair(2))
            safe_addstr(stdscr, row + 1, x, (icon_f + " " + day["desc"][:col_w - 4]).center(col_w - 1),
                        curses.color_pair(1))
            safe_addstr(stdscr, row + 2, x, temp_range.center(col_w - 1), curses.color_pair(3))


# ---------- pravý panel: kalendář (interaktivní, vlastní smyčka) ----------

def run_calendar(stdscr, y0, x0, width, height):
    today = datetime.date.today()
    year, month, day = today.year, today.month, today.day
    tab_held = False
    notes = load_notes()

    while True:
        h, w = height, width
        cal = calendar.monthcalendar(year, month)
        month_name = datetime.date(year, month, 1).strftime("%B %Y")

        for i in range(h):
            safe_addstr(stdscr, y0 + i, x0, " " * w)

        safe_addstr(stdscr, y0, x0 + w // 2 - len(month_name) // 2, month_name,
                    curses.color_pair(2) | curses.A_BOLD)

        days_header = " Mo   Tu   We   Th   Fr   Sa   Su"
        x_start = x0 + w // 2 - len(days_header) // 2
        safe_addstr(stdscr, y0 + 1, x_start, days_header, curses.color_pair(4))

        for week_i, week in enumerate(cal):
            for day_i, d in enumerate(week):
                if d == 0:
                    continue
                x = x_start + day_i * 5
                y = y0 + week_i + 2
                key = note_key(year, month, d)
                has_note = key in notes and notes[key]
                dot = "•" if has_note else " "
                is_today = (d == today.day and month == today.month and year == today.year)
                is_selected = (d == day)
                label = f"{d:2d}{dot} "
                if is_selected:
                    safe_addstr(stdscr, y, x, label, curses.color_pair(7) | curses.A_BOLD)
                elif is_today:
                    safe_addstr(stdscr, y, x, label, curses.color_pair(8) | curses.A_BOLD)
                elif has_note:
                    safe_addstr(stdscr, y, x, label, curses.color_pair(4))
                else:
                    safe_addstr(stdscr, y, x, label, curses.color_pair(1))

        note_y = y0 + len(cal) + 3
        selected_key = note_key(year, month, day)
        note_text = notes.get(selected_key, "")
        date_str = datetime.date(year, month, day).strftime("%d. %m. %Y")
        safe_addstr(stdscr, note_y, x0, date_str, curses.color_pair(2))
        safe_addstr(stdscr, note_y + 1, x0, (note_text if note_text else "no note")[:w],
                    curses.color_pair(1) if note_text else curses.color_pair(6))

        hints = "arrows: day   Tab+arrows: month   Enter: note   Esc: back"
        safe_addstr(stdscr, y0 + h - 1, x0 + w // 2 - len(hints) // 2, hints, curses.color_pair(2))

        stdscr.refresh()
        key = stdscr.getch()

        if key == 27:
            return
        elif key == ord('\t'):
            tab_held = True
        elif key == curses.KEY_LEFT:
            if tab_held:
                month -= 1
                if month < 1:
                    month, year = 12, year - 1
                day = min(day, calendar.monthrange(year, month)[1])
                tab_held = False
            else:
                new_day = day - 1
                if new_day < 1:
                    month -= 1
                    if month < 1:
                        month, year = 12, year - 1
                    day = calendar.monthrange(year, month)[1]
                else:
                    day = new_day
        elif key == curses.KEY_RIGHT:
            if tab_held:
                month += 1
                if month > 12:
                    month, year = 1, year + 1
                day = min(day, calendar.monthrange(year, month)[1])
                tab_held = False
            else:
                max_day = calendar.monthrange(year, month)[1]
                new_day = day + 1
                if new_day > max_day:
                    month += 1
                    if month > 12:
                        month, year = 1, year + 1
                    day = 1
                else:
                    day = new_day
        elif key == curses.KEY_UP:
            tab_held = False
            new_day = day - 7
            if new_day < 1:
                month -= 1
                if month < 1:
                    month, year = 12, year - 1
                day = calendar.monthrange(year, month)[1] + new_day
            else:
                day = new_day
        elif key == curses.KEY_DOWN:
            tab_held = False
            max_day = calendar.monthrange(year, month)[1]
            new_day = day + 7
            if new_day > max_day:
                month += 1
                if month > 12:
                    month, year = 1, year + 1
                day = new_day - max_day
            else:
                day = new_day
        elif key in (10, 13):
            tab_held = False
            curses.curs_set(1)
            existing = notes.get(selected_key, "")
            prompt = "> "
            input_y = note_y + 1
            safe_addstr(stdscr, input_y, x0, " " * w)
            safe_addstr(stdscr, input_y, x0, prompt + existing)
            stdscr.refresh()
            text = list(existing)
            while True:
                k = stdscr.getch()
                if k in (10, 13):
                    break
                elif k == 27:
                    text = list(existing)
                    break
                elif k in (curses.KEY_BACKSPACE, 127):
                    if text:
                        text.pop()
                elif 32 <= k <= 126:
                    text.append(chr(k))
                safe_addstr(stdscr, input_y, x0, " " * w)
                safe_addstr(stdscr, input_y, x0, prompt + "".join(text))
                stdscr.refresh()
            curses.curs_set(0)
            result = "".join(text).strip()
            if result:
                notes[selected_key] = result
            elif selected_key in notes:
                del notes[selected_key]
            save_notes(notes)
        else:
            tab_held = False


# ---------- pravý panel: timer (interaktivní, vlastní smyčka) ----------

def run_timer(stdscr, y0, x0, width, height):
    """6 prvků: 0-2 = HH/MM/SS, 3-5 = +5/+10/+20 quick-add.
    Enter na 0-2 potvrdí a spustí StickyTimer. Enter na 3-5 přičte minuty."""
    values = [0, 0, 0]
    labels = ["HH", "MM", "SS"]
    limits = [99, 59, 59]
    quick = [5, 10, 20]
    selected = 0

    while True:
        for i in range(height):
            safe_addstr(stdscr, y0 + i, x0, " " * width)

        title = "SET TIMER"
        cy = y0 + height // 2 - 3
        safe_addstr(stdscr, cy, x0 + width // 2 - len(title) // 2, title, curses.color_pair(2) | curses.A_BOLD)

        x_start = x0 + width // 2 - 10
        ty = cy + 2
        for i, (val, label) in enumerate(zip(values, labels)):
            segment = f" {val:02d} "
            x = x_start + i * 7
            style = curses.color_pair(3) | curses.A_BOLD | curses.A_REVERSE if i == selected \
                else curses.color_pair(1) | curses.A_BOLD
            safe_addstr(stdscr, ty, x, segment, style)
            if i < 2:
                safe_addstr(stdscr, ty, x + 4, " : ", curses.color_pair(1))
        for i, label in enumerate(labels):
            x = x_start + i * 7 + 1
            safe_addstr(stdscr, ty + 1, x, label, curses.color_pair(2) if i == selected else curses.color_pair(3))

        qy = ty + 3
        qx_start = x0 + width // 2 - 12
        for i, mins in enumerate(quick):
            idx = 3 + i
            label = f" +{mins}m "
            x = qx_start + i * 9
            style = curses.color_pair(3) | curses.A_BOLD | curses.A_REVERSE if idx == selected \
                else curses.color_pair(6)
            safe_addstr(stdscr, qy, x, label, style)

        hints = "left/right: pick   up/down: adjust   Enter: add/start   Esc: cancel"
        safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hints) // 2, hints, curses.color_pair(2))

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP and selected < 3:
            values[selected] = (values[selected] + 1) % (limits[selected] + 1)
        elif key == curses.KEY_DOWN and selected < 3:
            values[selected] = (values[selected] - 1) % (limits[selected] + 1)
        elif key == curses.KEY_RIGHT:
            selected = (selected + 1) % 6
        elif key == curses.KEY_LEFT:
            selected = (selected - 1) % 6
        elif key in (10, 13):
            if selected < 3:
                total = values[0] * 3600 + values[1] * 60 + values[2]
                if total > 0:
                    subprocess.Popen(["swaymsg", "exec",
                        f"kitty --class StickyTimer --override font_size=30 -e termdown {total}"])
                    return "started"
            else:
                add_min = quick[selected - 3]
                total = values[0] * 3600 + values[1] * 60 + values[2] + add_min * 60
                total = min(total, 99 * 3600 + 59 * 60 + 59)
                values[0] = total // 3600
                values[1] = (total % 3600) // 60
                values[2] = total % 60
        elif key == 27:
            return None


# ---------- pravý panel: connectivity chooser ----------

def get_wifi_info():
    return query_daemon("wifi")


def get_bt_info():
    return query_daemon("bt")


def launch_kitty_pane(command_list):
    """Spustí opravdový druhý kitty panel vedle dashboardu přes remote control."""
    subprocess.run(
        ["kitty", "@", "--to", f"unix:{KITTY_SOCKET}",
         "launch", "--type=window", "--location=vsplit", "--bias=78"] + command_list,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def run_connectivity(stdscr, y0, x0, width, height):
    selected = 0
    while True:
        for i in range(height):
            safe_addstr(stdscr, y0 + i, x0, " " * width)

        half = width // 2
        draw_box(stdscr, y0, x0, height - 1, half, selected == 0, "WiFi")
        draw_box(stdscr, y0, x0 + half, height - 1, width - half, selected == 1, "Bluetooth")

        mid = y0 + (height - 1) // 2

        wifi = get_wifi_info()
        if wifi:
            safe_addstr(stdscr, mid, x0 + half // 2 - len(wifi["ssid"]) // 2, wifi["ssid"],
                        curses.color_pair(4) | curses.A_BOLD)
            rssi = f"{wifi['rssi']} dBm"
            safe_addstr(stdscr, mid + 1, x0 + half // 2 - len(rssi) // 2, rssi, curses.color_pair(1))
        else:
            safe_addstr(stdscr, mid, x0 + half // 2 - 6, "disconnected", curses.color_pair(5))

        bt = get_bt_info()
        bx = x0 + half
        if bt:
            safe_addstr(stdscr, mid, bx + half // 2 - len(bt["name"]) // 2, bt["name"],
                        curses.color_pair(4) | curses.A_BOLD)
            bat = f"bat: {bt['battery']}" if bt.get("battery") else "connected"
            safe_addstr(stdscr, mid + 1, bx + half // 2 - len(bat) // 2, bat, curses.color_pair(1))
        else:
            safe_addstr(stdscr, mid, bx + half // 2 - 6, "disconnected", curses.color_pair(5))

        hints = "left/right: pick   Enter: open (real kitty panel)   Esc: back"
        safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hints) // 2, hints, curses.color_pair(2))
        stdscr.refresh()

        key = stdscr.getch()
        if key == 27:
            return
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord('\t')):
            selected = 1 - selected
        elif key in (10, 13):
            if selected == 0:
                launch_kitty_pane(["impala"])
            else:
                launch_kitty_pane(["bluetuith"])
            return


# ---------- pravý panel: app launcher (vlastní smyčka) ----------

def run_launcher(stdscr, y0, x0, width, height):
    apps = scan_desktop_apps()
    query = ""
    filtered = apps
    sel = 0
    curses.curs_set(1)

    while True:
        for i in range(height):
            safe_addstr(stdscr, y0 + i, x0, " " * width)

        prompt = f"> {query}"
        safe_addstr(stdscr, y0, x0, prompt, curses.color_pair(3) | curses.A_BOLD)

        list_y = y0 + 2
        for i, (name, _cmd) in enumerate(filtered[:height - 3]):
            style = curses.color_pair(3) | curses.A_REVERSE if i == sel else curses.color_pair(1)
            safe_addstr(stdscr, list_y + i, x0 + 2, name[:width - 4], style)

        hints = "type to search   up/down: pick   Enter: launch   Esc: back"
        safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hints) // 2, hints, curses.color_pair(2))
        stdscr.refresh()

        key = stdscr.getch()
        if key == 27:
            curses.curs_set(0)
            return
        elif key == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif key == curses.KEY_DOWN:
            sel = min(max(0, len(filtered) - 1), sel + 1)
        elif key in (curses.KEY_BACKSPACE, 127):
            query = query[:-1]
            filtered = [a for a in apps if query.lower() in a[0].lower()]
            sel = 0
        elif key in (10, 13):
            if filtered:
                cmd = filtered[sel][1]
                subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            curses.curs_set(0)
            return
        elif 32 <= key <= 126:
            query += chr(key)
            filtered = [a for a in apps if query.lower() in a[0].lower()]
            sel = 0


# ---------- sidebar ----------

def draw_sidebar(stdscr, items, selected, y0, x0, width, height, power_start):
    draw_box(stdscr, y0, x0, height, width, False)
    row = y0 + 1
    for i in range(power_start):
        name, kind, extra = items[i]
        label = f"{name}{extra}"
        style = curses.color_pair(3) | curses.A_REVERSE if i == selected else curses.color_pair(1)
        safe_addstr(stdscr, row, x0 + 2, label[:width - 4].ljust(width - 4), style)
        row += 1

    power_y = y0 + height - 1 - len(POWER_OPTIONS)
    safe_addstr(stdscr, power_y - 1, x0 + 2, "─" * (width - 4), curses.color_pair(6))
    for j, (key, name, _cmd) in enumerate(POWER_OPTIONS):
        idx = power_start + j
        label = f"[{key}] {name}"
        style = curses.color_pair(3) | curses.A_REVERSE if idx == selected else curses.color_pair(5)
        safe_addstr(stdscr, power_y + j, x0 + 2, label[:width - 4].ljust(width - 4), style)


# ---------- main ----------

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_RED, -1)
    curses.init_pair(6, curses.COLOR_BLACK + 8, -1)
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_WHITE)
    stdscr.keypad(True)

    apps = get_running_apps()
    weather_cache = query_daemon("weather")
    weather_extra = ""
    if weather_cache:
        weather_extra = f" [{weather_cache['temp']}°C {weather_icon(weather_cache['desc'])}]"

    sidebar_items = [("App Launcher", "launcher", "")]
    sidebar_items += [(name, "app", f" ({len(wins)})") for name, wins in sorted(apps.items())]
    sidebar_items += [
        ("Weather", "weather", weather_extra),
        ("Calendar", "calendar", ""),
        ("Timer", "timer", ""),
        ("Connectivity", "connectivity", ""),
    ]
    power_start = len(sidebar_items)
    for key, name, _cmd in POWER_OPTIONS:
        sidebar_items.append((name, "power", ""))

    sel_side = 1 if len(sidebar_items) > 1 else 0
    grid_sel = 0
    power_keys = {k: cmd for k, _n, cmd in POWER_OPTIONS}

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        side_w = max(w // 5, 20)

        draw_sidebar(stdscr, sidebar_items, sel_side, 0, 0, side_w, h - 1, power_start)

        name, kind, _extra = sidebar_items[sel_side]
        if kind == "app":
            windows = apps.get(name, [])
            draw_grid(stdscr, windows, grid_sel, 0, side_w, w - side_w, h - 1)
        elif kind == "weather":
            draw_weather(stdscr, 1, side_w, w - side_w, h - 2)
        elif kind == "launcher":
            safe_addstr(stdscr, h // 2, side_w + (w - side_w) // 2 - 12,
                        "Enter to search & launch apps", curses.color_pair(2))
        elif kind == "calendar":
            safe_addstr(stdscr, h // 2, side_w + (w - side_w) // 2 - 8,
                        "Enter to open calendar", curses.color_pair(2))
        elif kind == "timer":
            safe_addstr(stdscr, h // 2, side_w + (w - side_w) // 2 - 6,
                        "Enter to set timer", curses.color_pair(2))
        elif kind == "connectivity":
            safe_addstr(stdscr, h // 2, side_w + (w - side_w) // 2 - 9,
                        "Enter to open WiFi/BT", curses.color_pair(2))
        elif kind == "power":
            safe_addstr(stdscr, h // 2, side_w + (w - side_w) // 2 - 8,
                        "Enter or shortcut to confirm", curses.color_pair(5))

        hints = "TAB navigate   ENTER select   ESC close   l/s/o/r/p power"
        safe_addstr(stdscr, h - 1, w // 2 - len(hints) // 2, hints, curses.color_pair(2))

        stdscr.refresh()
        key = stdscr.getch()

        # globální power zkratky - fungují odkudkoliv v hlavní smyčce
        if key != -1 and 0 <= key < 256:
            ch = chr(key).lower()
            if ch in power_keys:
                subprocess.run(power_keys[ch])
                return

        if key == 27:
            return
        elif key == ord('\t'):
            sel_side = (sel_side + 1) % len(sidebar_items)
            grid_sel = 0
        elif key == curses.KEY_BTAB:
            sel_side = (sel_side - 1) % len(sidebar_items)
            grid_sel = 0
        elif key in (10, 13):
            name, kind, _extra = sidebar_items[sel_side]
            h, w = stdscr.getmaxyx()
            side_w = max(w // 5, 20)

            if kind == "app":
                windows = apps.get(name, [])
                if windows and 0 <= grid_sel < len(windows):
                    focus_window(windows[grid_sel]["con_id"])
                    return
            elif kind == "launcher":
                run_launcher(stdscr, 1, side_w, w - side_w, h - 2)
            elif kind == "calendar":
                run_calendar(stdscr, 1, side_w, w - side_w, h - 2)
            elif kind == "timer":
                result = run_timer(stdscr, 1, side_w, w - side_w, h - 2)
                if result == "started":
                    return
            elif kind == "connectivity":
                run_connectivity(stdscr, 1, side_w, w - side_w, h - 2)
            elif kind == "power":
                for _k, name_, cmd_ in POWER_OPTIONS:
                    if name_ == name:
                        subprocess.run(cmd_)
                        return


if __name__ == "__main__":
    curses.wrapper(main)
