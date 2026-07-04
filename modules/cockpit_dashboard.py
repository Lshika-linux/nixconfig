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
    """Vrátí { 'YYYY-MM-DD': [note1, note2, ...] }. Migruje starý formát
    (jeden string na den) na seznam, aby se nerozbily existující poznámky."""
    try:
        with open(NOTES_FILE) as f:
            raw = json.load(f)
    except Exception:
        return {}

    migrated = {}
    for k, v in raw.items():
        if isinstance(v, list):
            migrated[k] = [s for s in v if s]
        elif isinstance(v, str) and v:
            migrated[k] = [v]
        else:
            migrated[k] = []
    return migrated


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

def draw_weather_strip(stdscr, y0, x0, width, height):
    """Trvalý kompaktní blok počasí - vždy viditelný dole pod hlavním obsahem."""
    draw_box(stdscr, y0, x0, height, width, False, "Weather")
    data = query_daemon("weather")
    if not data:
        safe_addstr(stdscr, y0 + height // 2, x0 + width // 2 - 4, "no data", curses.color_pair(5))
        return

    icon = weather_icon(data["desc"])
    line1 = f"{data['city']}   {icon} {data['temp']}°C   {data['desc']}"
    safe_addstr(stdscr, y0 + 1, x0 + width // 2 - len(line1) // 2, line1,
                curses.color_pair(3) | curses.A_BOLD)

    line2 = f"feels {data['feels']}°C   wind {data['wind']} km/h   humidity {data['humidity']}%"
    safe_addstr(stdscr, y0 + 2, x0 + width // 2 - len(line2) // 2, line2, curses.color_pair(6))

    if data.get("forecast") and height >= 5:
        parts = []
        for day in data["forecast"]:
            date_parts = day["date"].split("-")
            date_short = f"{date_parts[2]}.{date_parts[1]}"
            parts.append(f"{date_short} {weather_icon(day['desc'])} {day['min']}-{day['max']}°C")
        line3 = "   ".join(parts)
        safe_addstr(stdscr, y0 + 3, x0 + width // 2 - len(line3) // 2, line3, curses.color_pair(1))


# ---------- pravý panel: kalendář (render + interaktivní smyčka) ----------

WEEKDAY_NAMES = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
NOTES_PANEL_H = 9  # kolik řádků dole je vyhrazeno na seznam poznámek


def render_calendar(stdscr, year, month, day, notes, y0, x0, width, height,
                     interactive=True, panel_mode=False, notes_sel=0):
    """Čistě vykreslení - používá se pro preview (na hover) i uvnitř run_calendar.
    panel_mode=True znamená, že fokus je v seznamu poznámek (ne na gridu dní)."""
    today = datetime.date.today()
    for i in range(height):
        safe_addstr(stdscr, y0 + i, x0, " " * width)

    cal = calendar.monthcalendar(year, month)
    month_name = datetime.date(year, month, 1).strftime("%B %Y")
    safe_addstr(stdscr, y0, x0 + width // 2 - len(month_name) // 2, month_name,
                curses.color_pair(2) | curses.A_BOLD)

    col_w = width // 7
    header_y = y0 + 2
    for i, wd in enumerate(WEEKDAY_NAMES):
        x = x0 + i * col_w
        safe_addstr(stdscr, header_y, x + col_w // 2 - 1, wd, curses.color_pair(4) | curses.A_BOLD)

    grid_top = header_y + 1
    grid_bottom = y0 + height - NOTES_PANEL_H - 2
    n_weeks = len(cal)
    row_h = max((grid_bottom - grid_top) // n_weeks, 3)

    for week_i, week in enumerate(cal):
        for day_i, d in enumerate(week):
            if d == 0:
                continue
            cx = x0 + day_i * col_w
            cy = grid_top + week_i * row_h
            key = note_key(year, month, d)
            day_notes_cell = notes.get(key, [])
            n_notes = len(day_notes_cell)
            is_today = (d == today.day and month == today.month and year == today.year)
            is_selected = (d == day)

            draw_box(stdscr, cy, cx, row_h, col_w, is_selected and not panel_mode)

            num_color = curses.color_pair(7) | curses.A_BOLD if is_selected \
                else curses.color_pair(8) | curses.A_BOLD if is_today \
                else curses.color_pair(1)
            safe_addstr(stdscr, cy + 1, cx + 2, f"{d:2d}", num_color)

            if n_notes and row_h > 2:
                dots = "•" * min(n_notes, 3) + (f" +{n_notes - 3}" if n_notes > 3 else "")
                safe_addstr(stdscr, cy + row_h - 2, cx + 2, dots[:col_w - 3], curses.color_pair(4))

    panel_y = grid_top + n_weeks * row_h + 1
    selected_key = note_key(year, month, day)
    day_notes = notes.get(selected_key, [])
    date_str = datetime.date(year, month, day).strftime("%d. %m. %Y")
    count_str = f"({len(day_notes)} notes)" if day_notes else "(no notes)"
    panel_title_color = curses.color_pair(3) | curses.A_BOLD if panel_mode else curses.color_pair(2) | curses.A_BOLD
    safe_addstr(stdscr, panel_y, x0, f"{date_str}  {count_str}", panel_title_color)

    max_visible = NOTES_PANEL_H - 3
    all_lines = day_notes + ["+ new note"]
    shown = all_lines[:max_visible]
    for i, note_text in enumerate(shown):
        is_new_line = (i == len(day_notes))
        is_sel = panel_mode and i == notes_sel
        if is_new_line:
            prefix = "> " if is_sel else "+ "
            color = curses.color_pair(3) | curses.A_BOLD if is_sel else curses.color_pair(6)
            text = "new note"
        else:
            prefix = "> " if is_sel else "- "
            color = curses.color_pair(7) | curses.A_BOLD if is_sel else curses.color_pair(1)
            text = note_text
        safe_addstr(stdscr, panel_y + 1 + i, x0 + 2, (prefix + text)[:width - 4], color)
    if len(all_lines) > max_visible:
        safe_addstr(stdscr, panel_y + 1 + max_visible, x0 + 2,
                    f"... +{len(all_lines) - max_visible} more", curses.color_pair(6))

    if not interactive:
        hints = "Enter to edit"
    elif panel_mode:
        hints = "up/down: pick note   Enter: edit/add   d: delete   Esc: back to calendar"
    else:
        hints = "arrows: day   Tab+arrows: month   Enter: notes   Esc: back"
    safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hints) // 2, hints, curses.color_pair(2))
    return panel_y


def run_calendar(stdscr, y0, x0, width, height):
    today = datetime.date.today()
    year, month, day = today.year, today.month, today.day
    tab_held = False
    notes = load_notes()
    panel_mode = False
    notes_sel = 0

    while True:
        w = width
        selected_key = note_key(year, month, day)
        day_notes = notes.get(selected_key, [])

        render_calendar(stdscr, year, month, day, notes, y0, x0, width, height,
                         panel_mode=panel_mode, notes_sel=notes_sel)
        stdscr.refresh()
        key = stdscr.getch()

        if key == 27:
            if panel_mode:
                panel_mode = False
            else:
                return

        elif not panel_mode and key == ord('\t'):
            tab_held = True

        elif not panel_mode and key == curses.KEY_LEFT:
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

        elif not panel_mode and key == curses.KEY_RIGHT:
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

        elif not panel_mode and key == curses.KEY_UP:
            tab_held = False
            new_day = day - 7
            if new_day < 1:
                month -= 1
                if month < 1:
                    month, year = 12, year - 1
                day = calendar.monthrange(year, month)[1] + new_day
            else:
                day = new_day

        elif not panel_mode and key == curses.KEY_DOWN:
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

        elif not panel_mode and key in (10, 13):
            # vstup do navigace mezi poznámkami daného dne
            tab_held = False
            panel_mode = True
            notes_sel = 0

        elif panel_mode and key == curses.KEY_UP:
            notes_sel = max(0, notes_sel - 1)

        elif panel_mode and key == curses.KEY_DOWN:
            notes_sel = min(len(day_notes), notes_sel + 1)  # poslední index = "+ new note"

        elif panel_mode and key in (ord('d'), ord('D')):
            if day_notes and notes_sel < len(day_notes):
                day_notes.pop(notes_sel)
                notes[selected_key] = day_notes
                save_notes(notes)
                notes_sel = max(0, min(notes_sel, len(day_notes)))

        elif panel_mode and key in (10, 13):
            is_new = (notes_sel == len(day_notes))
            existing = "" if is_new else day_notes[notes_sel]
            prompt = "new note> " if is_new else "edit note> "

            curses.curs_set(1)
            input_y = y0 + height - 2
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
            if is_new:
                if result:
                    day_notes.append(result)
            else:
                if result:
                    day_notes[notes_sel] = result
                else:
                    day_notes.pop(notes_sel)
                    notes_sel = max(0, notes_sel - 1)
            notes[selected_key] = day_notes
            save_notes(notes)

        else:
            tab_held = False


# ---------- pravý panel: timer (render + interaktivní smyčka) ----------

QUICK_MINUTES = [5, 10, 20]
TIMER_LABELS = ["HH", "MM", "SS"]


def render_timer(stdscr, values, selected, y0, x0, width, height, interactive=True):
    for i in range(height):
        safe_addstr(stdscr, y0 + i, x0, " " * width)

    title = "SET TIMER"
    cy = y0 + height // 2 - 3
    safe_addstr(stdscr, cy, x0 + width // 2 - len(title) // 2, title, curses.color_pair(2) | curses.A_BOLD)

    x_start = x0 + width // 2 - 10
    ty = cy + 2
    for i, (val, label) in enumerate(zip(values, TIMER_LABELS)):
        segment = f" {val:02d} "
        x = x_start + i * 7
        style = curses.color_pair(3) | curses.A_BOLD | curses.A_REVERSE if (interactive and i == selected) \
            else curses.color_pair(1) | curses.A_BOLD
        safe_addstr(stdscr, ty, x, segment, style)
        if i < 2:
            safe_addstr(stdscr, ty, x + 4, " : ", curses.color_pair(1))
    for i, label in enumerate(TIMER_LABELS):
        x = x_start + i * 7 + 1
        safe_addstr(stdscr, ty + 1, x, label,
                    curses.color_pair(2) if (interactive and i == selected) else curses.color_pair(3))

    qy = ty + 3
    qx_start = x0 + width // 2 - 12
    for i, mins in enumerate(QUICK_MINUTES):
        idx = 3 + i
        label = f" +{mins}m "
        x = qx_start + i * 9
        style = curses.color_pair(3) | curses.A_BOLD | curses.A_REVERSE if (interactive and idx == selected) \
            else curses.color_pair(6)
        safe_addstr(stdscr, qy, x, label, style)

    hints = "left/right: pick   up/down: adjust   Enter: add/start   Esc: cancel" if interactive \
        else "Enter to set timer"
    safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hints) // 2, hints, curses.color_pair(2))


def run_timer(stdscr, y0, x0, width, height):
    """6 prvků: 0-2 = HH/MM/SS, 3-5 = +5/+10/+20 quick-add.
    Enter na 0-2 potvrdí a spustí StickyTimer. Enter na 3-5 přičte minuty."""
    values = [0, 0, 0]
    limits = [99, 59, 59]
    quick = QUICK_MINUTES
    selected = 0

    while True:
        render_timer(stdscr, values, selected, y0, x0, width, height)
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


# ---------- connectivity: pinnuté WiFi/BT boxíky nad power menu ----------

def get_wifi_info():
    return query_daemon("wifi")


def get_bt_info():
    return query_daemon("bt")


def wifi_dbm_to_percent(dbm):
    """Standardní odhad kvality signálu z dBm (stejná formule jako NetworkManager)."""
    try:
        pct = 2 * (int(dbm) + 100)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, pct))


def launch_kitty_pane(command_list):
    """Spustí opravdový druhý kitty panel vedle dashboardu přes remote control."""
    subprocess.run(
        ["kitty", "@", "--to", f"unix:{KITTY_SOCKET}",
         "launch", "--type=window", "--location=vsplit", "--bias=78"] + command_list,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ---------- pravý panel: app launcher (render + vlastní smyčka) ----------

def render_launcher(stdscr, query, filtered, sel, y0, x0, width, height, interactive=True):
    for i in range(height):
        safe_addstr(stdscr, y0 + i, x0, " " * width)

    prompt = f"> {query}"
    safe_addstr(stdscr, y0, x0, prompt, curses.color_pair(3) | curses.A_BOLD)

    list_y = y0 + 2
    for i, (name, _cmd) in enumerate(filtered[:height - 3]):
        style = curses.color_pair(3) | curses.A_REVERSE if (interactive and i == sel) else curses.color_pair(1)
        safe_addstr(stdscr, list_y + i, x0 + 2, name[:width - 4], style)

    hints = "type to search   up/down: pick   Enter: launch   Esc: back" if interactive \
        else "Enter to search"
    safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hints) // 2, hints, curses.color_pair(2))


def run_launcher(stdscr, y0, x0, width, height):
    apps = scan_desktop_apps()
    query = ""
    filtered = apps
    sel = 0
    curses.curs_set(1)

    while True:
        render_launcher(stdscr, query, filtered, sel, y0, x0, width, height)
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

def draw_sidebar(stdscr, items, selected, y0, x0, width, height, power_start,
                  desktop_apps_preview, focused=True):
    draw_box(stdscr, y0, x0, height, width, focused)

    power_block_h = len(POWER_OPTIONS) + 2
    conn_block_h = 7  # 2x box (výška 3) + 1 řádek odděleného odstupu
    content_h = height - 2 - power_block_h - conn_block_h
    band_h = max(content_h // 3, 5)

    band1_y = y0 + 1
    band2_y = band1_y + band_h
    band3_y = band2_y + band_h

    app_items = [(i, it) for i, it in enumerate(items) if it[1] == "app"]
    func_items = [(i, it) for i, it in enumerate(items) if it[1] in ("calendar", "timer")]

    # --- horní třetina: App Launcher - vždy vidět, search pole + náhled seznamu ---
    safe_addstr(stdscr, band1_y, x0 + 2, "── Launcher ──"[:width - 4], curses.color_pair(6))
    launcher_focused = (selected == 0)
    prompt_style = curses.color_pair(3) | curses.A_REVERSE if launcher_focused else curses.color_pair(1)
    safe_addstr(stdscr, band1_y + 1, x0 + 2, "> search apps"[:width - 4].ljust(width - 4), prompt_style)
    for i, (name, _cmd) in enumerate(desktop_apps_preview[:band_h - 3]):
        safe_addstr(stdscr, band1_y + 2 + i, x0 + 2, name[:width - 4], curses.color_pair(6))

    # --- prostřední třetina: Window Switcher - vždy vidět, scroll podle výběru ---
    safe_addstr(stdscr, band2_y, x0 + 2, "── Windows ──"[:width - 4], curses.color_pair(6))
    visible_apps = band_h - 1
    sel_local = next((n for n, (i, _it) in enumerate(app_items) if i == selected), None)
    offset = 0
    if sel_local is not None and len(app_items) > visible_apps:
        offset = max(0, min(sel_local - visible_apps // 2, len(app_items) - visible_apps))
    for n, (i, (name, _kind, extra)) in enumerate(app_items[offset:offset + visible_apps]):
        row = band2_y + 1 + n
        label = f"{name}{extra}"
        style = curses.color_pair(3) | curses.A_REVERSE if i == selected else curses.color_pair(1)
        safe_addstr(stdscr, row, x0 + 2, label[:width - 4].ljust(width - 4), style)
    if not app_items:
        safe_addstr(stdscr, band2_y + 1, x0 + 2, "(no windows)", curses.color_pair(6))

    # --- dolní třetina: zbytek funkcionalit ---
    safe_addstr(stdscr, band3_y, x0 + 2, "── More ──"[:width - 4], curses.color_pair(6))
    for n, (i, (name, _kind, extra)) in enumerate(func_items):
        row = band3_y + 1 + n
        style = curses.color_pair(3) | curses.A_REVERSE if i == selected else curses.color_pair(1)
        safe_addstr(stdscr, row, x0 + 2, f"{name}{extra}"[:width - 4].ljust(width - 4), style)

    # --- pinnuté WiFi/BT boxíky, hned nad PowerMenu ---
    power_y = y0 + height - 1 - len(POWER_OPTIONS)
    wifi_idx = next((i for i, it in enumerate(items) if it[1] == "wifi"), None)
    bt_idx = next((i for i, it in enumerate(items) if it[1] == "bt"), None)

    bt_box_y = power_y - 1 - 3
    wifi_box_y = bt_box_y - 3

    wifi_data = get_wifi_info()
    draw_box(stdscr, wifi_box_y, x0, 3, width, selected == wifi_idx, "WiFi")
    if wifi_data:
        pct = wifi_dbm_to_percent(wifi_data.get("rssi"))
        pct_str = f"{pct}%" if pct is not None else "?"
        safe_addstr(stdscr, wifi_box_y + 1, x0 + 2, f"● {pct_str}", curses.color_pair(4) | curses.A_BOLD)
    else:
        safe_addstr(stdscr, wifi_box_y + 1, x0 + 2, "○ --", curses.color_pair(5))

    bt_data = get_bt_info()
    draw_box(stdscr, bt_box_y, x0, 3, width, selected == bt_idx, "Bluetooth")
    if bt_data:
        bat_str = bt_data.get("battery") or "--"
        safe_addstr(stdscr, bt_box_y + 1, x0 + 2, f"● {bat_str}", curses.color_pair(4) | curses.A_BOLD)
    else:
        safe_addstr(stdscr, bt_box_y + 1, x0 + 2, "○ --", curses.color_pair(5))

    # --- pinnuté PowerMenu, beze změny ---
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

    sidebar_items = [("App Launcher", "launcher", "")]
    sidebar_items += [(name, "app", f" ({len(wins)})") for name, wins in sorted(apps.items())]
    sidebar_items += [
        ("Calendar", "calendar", ""),
        ("Timer", "timer", ""),
        ("WiFi", "wifi", ""),
        ("Bluetooth", "bt", ""),
    ]
    power_start = len(sidebar_items)
    for key, name, _cmd in POWER_OPTIONS:
        sidebar_items.append((name, "power", ""))

    sel_side = 1 if len(sidebar_items) > 1 else 0
    grid_sel = 0
    power_keys = {k: cmd for k, _n, cmd in POWER_OPTIONS}

    desktop_apps_cache = scan_desktop_apps()
    default_timer_values = [0, 0, 0]
    WEATHER_STRIP_H = 6

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        side_w = max(w // 5, 20)
        cx0, cy0 = side_w + 1, 1
        cwidth = (w - side_w) - 2
        cheight = (h - 3) - WEATHER_STRIP_H
        weather_y = cy0 + cheight

        draw_sidebar(stdscr, sidebar_items, sel_side, 0, 0, side_w, h - 1, power_start,
                     desktop_apps_cache, focused=True)
        draw_box(stdscr, 0, side_w, h - 1, w - side_w, False)
        draw_weather_strip(stdscr, weather_y, cx0, cwidth, WEATHER_STRIP_H)

        name, kind, _extra = sidebar_items[sel_side]
        if kind == "app":
            windows = apps.get(name, [])
            draw_grid(stdscr, windows, grid_sel, cy0, cx0, cwidth, cheight)
        elif kind == "launcher":
            render_launcher(stdscr, "", desktop_apps_cache, -1, cy0, cx0, cwidth, cheight, interactive=False)
        elif kind == "calendar":
            today = datetime.date.today()
            render_calendar(stdscr, today.year, today.month, today.day, load_notes(),
                             cy0, cx0, cwidth, cheight, interactive=False)
        elif kind == "timer":
            render_timer(stdscr, default_timer_values, -1, cy0, cx0, cwidth, cheight, interactive=False)
        elif kind in ("wifi", "bt"):
            safe_addstr(stdscr, h // 2, cx0 + cwidth // 2 - 10,
                        "Enter to open a real terminal panel", curses.color_pair(2))
        elif kind == "power":
            safe_addstr(stdscr, h // 2, cx0 + cwidth // 2 - 12,
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
            cx0, cy0 = side_w + 1, 1
            cwidth, cheight = (w - side_w) - 2, (h - 3) - WEATHER_STRIP_H

            if kind == "app":
                windows = apps.get(name, [])
                if windows and 0 <= grid_sel < len(windows):
                    focus_window(windows[grid_sel]["con_id"])
                    return
            elif kind in ("launcher", "calendar", "timer"):
                # fokus se přesouvá do obsahu - sidebar zešedne, obsah dostane zvýrazněný rámeček
                draw_sidebar(stdscr, sidebar_items, sel_side, 0, 0, side_w, h - 1, power_start,
                             desktop_apps_cache, focused=False)
                draw_box(stdscr, 0, side_w, h - 1, w - side_w, True)
                stdscr.refresh()

                if kind == "launcher":
                    run_launcher(stdscr, cy0, cx0, cwidth, cheight)
                elif kind == "calendar":
                    run_calendar(stdscr, cy0, cx0, cwidth, cheight)
                elif kind == "timer":
                    result = run_timer(stdscr, cy0, cx0, cwidth, cheight)
                    if result == "started":
                        return
            elif kind == "wifi":
                launch_kitty_pane(["impala"])
            elif kind == "bt":
                launch_kitty_pane(["bluetuith"])
            elif kind == "power":
                for _k, name_, cmd_ in POWER_OPTIONS:
                    if name_ == name:
                        subprocess.run(cmd_)
                        return


if __name__ == "__main__":
    curses.wrapper(main)
