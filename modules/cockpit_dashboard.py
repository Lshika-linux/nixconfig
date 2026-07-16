#!/usr/bin/env python3
"""
cockpit_dashboard.py — fullscreen dashboard (Win+grave).

Levý sloupec (1/5): AppLauncher (úplně nahoře) -> workspace switcher ->
pinnuté Timer/WiFi/Bluetooth boxíky -> pinnuté PowerMenu dole.
Fokus při startu naskočí na první workspace (AppLauncher je jen o Shift+Tab výš).

Pravá plocha (4/5): kontextový obsah podle vybrané položky - náhled
workspace, launcher, power preview - a dole napevno pruh Calendar (pasivní
náhled měsíce) + Weather.

Window switcher je záměrně na úrovni WORKSPACE, ne jednotlivého okna -
cockpit_photographer.py fotí celý workspace najednou (grim to umí jen na to,
co je aktuálně vidět, takže se to hodí lépe než foto po okně), a náhled je
tak jeden konzistentní obrázek s předvídatelným poměrem stran místo gridu
různě velkých oken. Cena: nejde skočit na konkrétní okno uvnitř workspace
s víc oknama, jen na celý workspace (Enter = swaymsg workspace number N).

Calendar NENÍ v sidebaru / Tab cyklení - je jen ten pasivní náhled dole a
klávesa Ctrl+K, co odkudkoliv otevře interaktivní overlay (run_calendar)
přes hlavní obsahovou plochu.

Timer je pinnutý boxík (jako WiFi/BT) - žádný samostatný fokus mode, h:m:s
se nastavuje šipkama přímo když je boxík vybraný přes Tab, Enter spustí
StickyTimer (termdown v kitty) a zavře dashboard.

Connectivity (WiFi/BT) je jediná věc, co NEJDE vykreslit v curses - impala/
bluetuith jsou vlastní interaktivní TUI. Řeší se přes kitty remote control:
dashboard běží v kitty s --listen-on, a při volbě WiFi/BT se vedle spustí
OPRAVDOVÝ druhý kitty panel (kitty @ launch --location=vsplit) se skutečným
impala/bluetuith procesem. Žádná emulace terminálu, je to nativní kitty split.

PowerMenu jde spustit odkudkoliv v dashboardu klávesou Ctrl+L/O/R/P, navíc
je i součástí Tab cyklení jako pinnuté položky dole v levém sloupci.
"""
import curses
import subprocess
import json
import os
import calendar
import datetime
import threading
import time
import re
import base64

from cockpit_common import query_daemon

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, "scripts_sway")
NOTES_FILE = os.path.expanduser("~/.local/share/calendar_notes.json")

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

def ctrl(letter):
    """Kód, co getch() vrátí pro Ctrl+písmeno (1-26, netisknutelné - nikdy
    nekoliduje s běžným psaním textu, na rozdíl od Shift)."""
    return ord(letter.upper()) - 64


POWER_OPTIONS = [
    ("L", "Lock", ["bash", os.path.join(SCRIPTS, "lock.sh")]),
    ("O", "Logout", ["swaymsg", "exit"]),
    ("R", "Reboot", ["systemctl", "reboot"]),
    ("P", "Shutdown", ["systemctl", "poweroff"]),
]

# Poznámka: obyčejné unicode emoji, aby fungovaly bez závislosti na nerd fontu.
# Pokud chceš nerd-font ikony (sedí líp k tvému stylu u connectivity.py), stačí je tu vyměnit.
POWER_ICONS = {
    "Lock": "🔒",
    "Logout": "🚪",
    "Reboot": "🔁",
    "Shutdown": "⏻",
}


def draw_power_preview(stdscr, name, y0, x0, width, height):
    """Velká ikonka + rozšířený nadpis - curses neumí škálovat font,
    takže 'velké' = výrazný glyph + prostor kolem + roztažené písmenka."""
    icon = POWER_ICONS.get(name, "?")
    danger = name in ("Shutdown", "Reboot", "Logout")
    color = curses.color_pair(5) | curses.A_BOLD if danger else curses.color_pair(3) | curses.A_BOLD

    cy = y0 + height // 2 - 2
    safe_addstr(stdscr, cy, x0 + width // 2 - 1, icon, color)

    label = " ".join(name.upper())
    safe_addstr(stdscr, cy + 3, x0 + width // 2 - len(label) // 2, label, color)

    shortcut = next((k for k, n, _c in POWER_OPTIONS if n == name), "?")
    hint = f"Enter or [^{shortcut}] to confirm"
    safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hint) // 2, hint, curses.color_pair(2))


# ---------- weather (z weather.py) ----------

def weather_icon(desc):
    """VS16 (\ufe0f) na konci žádá emoji-presentation formu místo textové -
    tvůj PowerMenu už plain emoji (🔒💤🚪) renderuje bez problémů, takže by tohle
    mělo dát barevnější/větší ikonky než ty tenké textové glyphy (☀ bez VS16).
    Riziko: pokud font/kitty nemá barevný emoji fallback, může se místo toho
    objevit tofu čtvereček nebo se ikonka stane 2 buňky širokou a rozjede
    zarovnání vedle sebe stojících řádků - kdyby se to stalo, dej vědět a
    vrátíme se k plain textovým glyphům (bez \ufe0f)."""
    desc = desc.lower()
    if "thunder" in desc: return "⛈️"
    if "snow" in desc: return "❄️"
    if "rain" in desc or "drizzle" in desc: return "🌧️"
    if "cloud" in desc or "overcast" in desc: return "☁️"
    if "fog" in desc or "mist" in desc: return "🌫️"
    if "sunny" in desc or "clear" in desc: return "☀️"
    if "partly" in desc: return "⛅"
    return "~"


# ---------- sway tree / running apps ----------

def get_workspaces():
    """swaymsg -t get_workspaces vrací num/name/rect/focused/visible/output
    rovnou - žádné procházení stromu potřeba (na rozdíl od starého
    get_running_apps, co lezlo po celém stromu a groupovalo podle app_id)."""
    try:
        r = subprocess.run(["swaymsg", "-t", "get_workspaces"],
                            capture_output=True, text=True, timeout=2)
        return json.loads(r.stdout)
    except Exception:
        return []


def switch_workspace(num):
    subprocess.run(["swaymsg", "workspace", "number", str(num)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------- náhledy oken (kitty graphics protocol) ----------
#
# cockpit_photographer.py fotí okna na pozadí a ukládá PNG do THUMB_DIR
# podle con_id. Curses samo o sobě neumí vykreslit bitmapu - je to jen
# znaková mřížka. Kitty graphics protocol je escape sekvence (\x1b_G...\x1b\\),
# co terminálu řekne "polož sem obrázek", mimo curses úplně.
#
# Sixel a half-block truecolor fallback (pro terminály bez kitty protokolu,
# např. foot přes sixel) jsou připravené jako stuby - zatím neimplementované,
# ať se neladí tři netestované věci najednou.
#
# Důležité detaily, co dělají rozdíl mezi "funguje" a "rozbije to klávesnici":
#  - `q=2` na každém příkazu = potlačí odpověď z kitty. Bez toho by kitty
#    posílala vlastní APC odpovědi do STEJNÉHO vstupního proudu, ze kterého
#    curses čte klávesy přes getch() - reálné riziko rozbití vstupu.
#  - Placement se dělá cursor-position + escape, MIMO curses. Proto se volá
#    až PO stdscr.refresh() v hlavní smyčce, ne uvnitř draw_workspace_preview() - curses
#    interně trackuje pozici kurzoru pro optimalizaci, a raw zápis doprostřed
#    curses cyklu by ho mohl rozhodit.
#  - Žádné cachování podle image id (`i=`) - první verze si nechávala obrázek
#    nahraný v kitty a jen ho přes id znovu "pokládala", což zmizelo po
#    prvním framu (nejspíš `d=A` smaže i podkladová data, ne jen placement -
#    kitty dokumentace k tomu není 100% jednoznačná a nechci na tom stavět).
#    Místo toho `a=T` (transmit+display v jednom) pošle celý PNG znovu
#    každý frame. PNG jsou už zmenšené photographerem na max 480px, takže
#    re-transmit 3x/s je levný a tahle nejednoznačnost protokolu nás nezajímá.
#  - `t=f` = kitty si obrázek přečte ze souboru SAMO (payload je jen
#    base64 cesta k souboru, ne celý PNG) - nemusíme nic dekódovat/chunkovat
#    v Pythonu a nepotřebujeme žádnou image knihovnu.

KITTY_AVAILABLE = "KITTY_WINDOW_ID" in os.environ
THUMB_DIR = os.path.expanduser("~/.cache/cockpit/thumbs")


def _kitty_write(data: bytes):
    try:
        os.write(1, data)
    except OSError:
        pass


def _kitty_send(control, payload=b""):
    chunk = f"\x1b_G{control},q=2".encode()
    if payload:
        chunk += b";" + payload
    chunk += b"\x1b\\"
    _kitty_write(chunk)


def _kitty_clear_placements():
    _kitty_send("a=d,d=A")


def close_self():
    """Proaktivně zabije vlastní kitty okno přes swaymsg - STEJNÝ mechanismus,
    co už cockpit_dashboard_toggle.sh používá pro ruční zavření (Win+grave
    podruhé), takže víme, že funguje spolehlivě a rychle.

    Důvod, proč nestačí prostě `return` a nechat proces doběhnout: dashboard
    má `fullscreen enable` for_window pravidlo. Když se z launcheru spustí
    appka, sway ji vytvoří na tom samém workspace, ale dokud dashboardovo
    okno fyzicky nezmizí, sway (`popup_during_fullscreen smart`, výchozí
    hodnota) může dashboard "chytře" odfullscreenovat a ukázat ho tiled
    vedle ještě nenaběhlé appky - tenhle přechod je vázaný na to, kdy sway
    fakticky zaregistruje zavření okna, ne na to, kdy Python doběhne k
    `return`. Proaktivní kill hned při rozhodnutí (místo čekání na reaktivní
    řetězec proces-exit -> kitty-zavře-okno -> sway-si-všimne) dashboard
    smázne z obrazovky okamžitě, bez ohledu na to, jak dlouho appka startuje."""
    subprocess.run(["swaymsg", '[app_id="CockpitDashboard"] kill'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# Terminálová buňka NENÍ čtvercová - typický monospace font je zhruba
# 2x vyšší než širší. c=/r= v kitty protokolu natáhne obrázek přesně na
# daný počet sloupců/řádků BEZ ohledu na poměr stran zdrojového obrázku,
# takže vysoké/úzké okno (portrait) se bez korekce viditelně zdeformuje.
CELL_ASPECT = 2.0  # výška buňky / šířka buňky, v "pixelových" jednotkách


def _fit_aspect(avail_w, avail_h, src_w, src_h):
    """Największí (c, r) v buněčných jednotkách, co se vejde do avail_w x
    avail_h a zachová poměr stran src_w:src_h. Vrací i (offset_x, offset_y)
    pro vycentrování v původně vyhrazeném prostoru."""
    if not src_w or not src_h:
        return avail_w, avail_h, 0, 0
    box_w_px = avail_w
    box_h_px = avail_h * CELL_ASPECT
    src_aspect = src_w / src_h
    if src_aspect > box_w_px / box_h_px:
        target_w_px = box_w_px
        target_h_px = box_w_px / src_aspect
    else:
        target_h_px = box_h_px
        target_w_px = box_h_px * src_aspect
    c = max(1, round(target_w_px))
    r = max(1, round(target_h_px / CELL_ASPECT))
    offset_x = max((avail_w - c) // 2, 0)
    offset_y = max((avail_h - r) // 2, 0)
    return c, r, offset_x, offset_y


def render_kitty_thumbnails(pending):
    """pending = [(key, y, x, h, w, rect_w, rect_h), ...] - key je jméno
    souboru bez přípony v THUMB_DIR (např. "ws_3" pro workspace 3). Volá se
    AŽ PO stdscr.refresh().

    Záměrně BEZ cachování podle image id: `a=T` (transmit+display v jednom)
    pošle a rovnou zobrazí obrázek nanovo pokaždé, žádné spoléhání na to,
    jestli d=A maže i uloženou obrazovou data nebo jen placement - ať je to
    tak nebo tak, tenhle přístup na tom nezávisí. PNG jsou navíc už zmenšené
    photographerem na max 960px, takže re-transmit 3x/s je levný."""
    if not KITTY_AVAILABLE:
        return
    _kitty_clear_placements()
    for key, y, x, h, w, rect_w, rect_h in pending:
        if h < 2 or w < 2:
            continue
        path = os.path.join(THUMB_DIR, f"{key}.png")
        if not os.path.exists(path):
            continue
        c, r, off_x, off_y = _fit_aspect(w, h, rect_w, rect_h)
        b64path = base64.b64encode(path.encode()).decode()
        _kitty_write(f"\x1b[{y + off_y + 1};{x + off_x + 1}H".encode())
        _kitty_send(f"a=T,f=100,t=f,c={c},r={r}", b64path.encode())


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


_notes_cache = {"data": {}, "ts": 0.0}


def load_notes_cached():
    """Pro pasivní strip dole, co se překresluje každých 300ms - není důvod
    číst soubor z disku tak často, poznámky se stejně nemění mimo run_calendar."""
    now = time.time()
    if now - _notes_cache["ts"] > 2:
        _notes_cache["data"] = load_notes()
        _notes_cache["ts"] = now
    return _notes_cache["data"]


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


# ---------- pravý panel: náhled workspace ----------

def draw_workspace_preview(stdscr, ws, y0, x0, width, height):
    """Jeden náhled na celý (aktuálně vybraný) workspace, ne grid. Vrací
    pending thumbnail list (0 nebo 1 prvek) pro render_kitty_thumbnails() -
    ten se musí zavolat AŽ PO stdscr.refresh()."""
    if ws is None:
        safe_addstr(stdscr, y0 + height // 2, x0 + width // 2 - 6, "no workspace", curses.color_pair(5))
        return []

    draw_box(stdscr, y0, x0, height, width, False, ws.get("name", "?"))
    rect = ws.get("rect", {})
    dims = f"{rect.get('width', '?')}x{rect.get('height', '?')}"

    img_y, img_x = y0 + 1, x0 + 1
    img_h, img_w = height - 3, width - 2
    if KITTY_AVAILABLE and img_h >= 2 and img_w >= 2:
        dims_y = y0 + height - 2
        safe_addstr(stdscr, dims_y, x0 + width // 2 - len(dims) // 2, dims, curses.color_pair(6))
        key = f"ws_{ws['num']}"
        return [(key, img_y, img_x, img_h, img_w, rect.get("width") or 0, rect.get("height") or 0)]
    else:
        safe_addstr(stdscr, y0 + height // 2, x0 + width // 2 - len(dims) // 2, dims, curses.color_pair(6))
        return []


# ---------- pravý panel: weather ----------

def draw_weather_strip(stdscr, y0, x0, width, height):
    """Trvalý kompaktní blok počasí - vždy viditelný dole pod hlavním obsahem.
    Obsah (max 3 řádky) se vertikálně centruje v dostupné výšce boxu."""
    draw_box(stdscr, y0, x0, height, width, False, "Weather")
    data = query_daemon("weather")
    if not data:
        safe_addstr(stdscr, y0 + height // 2, x0 + width // 2 - 4, "no data", curses.color_pair(5))
        return

    has_forecast = bool(data.get("forecast")) and height >= 5
    n_lines = 3 if has_forecast else 2
    content_rows = height - 2
    start = y0 + 1 + max((content_rows - n_lines) // 2, 0)

    icon = weather_icon(data["desc"])
    line1 = f"{data['city']}   {icon} {data['temp']}°C   {data['desc']}"
    safe_addstr(stdscr, start, x0 + width // 2 - len(line1) // 2, line1,
                curses.color_pair(3) | curses.A_BOLD)

    line2 = f"feels {data['feels']}°C   wind {data['wind']} km/h   humidity {data['humidity']}%"
    safe_addstr(stdscr, start + 1, x0 + width // 2 - len(line2) // 2, line2, curses.color_pair(6))

    if has_forecast:
        parts = []
        for day in data["forecast"]:
            date_parts = day["date"].split("-")
            date_short = f"{date_parts[2]}.{date_parts[1]}"
            parts.append(f"{date_short} {weather_icon(day['desc'])} {day['min']}-{day['max']}°C")
        line3 = "   ".join(parts)
        safe_addstr(stdscr, start + 2, x0 + width // 2 - len(line3) // 2, line3, curses.color_pair(1))


# ---------- pravý panel: kompaktní kalendář vedle weather (pasivní náhled) ----------

def render_calendar_strip(stdscr, year, month, today_day, notes, y0, x0, width, height):
    """Pasivní náhled celého měsíce, pořád vidět vedle Weather. Box má vlastní
    titulek "Calendar [^K]" v horním rámečku (stejně jako "Weather"), hlavička
    dnů (Mo..Su) je normální řádek uvnitř boxu nad mřížkou. Zbylý prostor nad
    6 týdny + hlavičkou se rozloží jako padding, ať mřížka nelepí nahoře."""
    draw_box(stdscr, y0, x0, height, width, False, "Calendar [^K]")
    weeks = calendar.monthcalendar(year, month)
    while len(weeks) < 6:
        weeks.append([0] * 7)

    col_w = max(min(width // 7, 6), 3)
    grid_w = col_w * 7
    grid_x0 = x0 + 1 + max((width - 2 - grid_w) // 2, 0)
    content_rows = height - 2
    pad_top = max((content_rows - 8) // 2, 0)  # 8 = 1 volný řádek + hlavička + 6 týdnů
    header_y = y0 + 1 + pad_top + 1
    row0 = header_y + 1

    for i, wd in enumerate(WEEKDAY_NAMES):
        x = grid_x0 + i * col_w + col_w // 2 - 1
        safe_addstr(stdscr, header_y, x, wd, curses.color_pair(4) | curses.A_BOLD)

    notes_days = set()
    for k, v in notes.items():
        if not v:
            continue
        try:
            ky, km, kd = (int(p) for p in k.split("-"))
        except ValueError:
            continue
        if ky == year and km == month:
            notes_days.add(kd)

    for row in range(6):
        week = weeks[row] if row < len(weeks) else [0] * 7
        for col, d in enumerate(week):
            if d == 0:
                continue
            x = grid_x0 + col * col_w + col_w // 2 - 1
            y = row0 + row
            num_str = str(d)
            style = curses.color_pair(3) | curses.A_REVERSE if d == today_day else curses.color_pair(1) | curses.A_BOLD
            safe_addstr(stdscr, y, x, num_str[:col_w], style)
            if d in notes_days and len(num_str) < col_w:
                safe_addstr(stdscr, y, x + len(num_str), "●", curses.color_pair(4) | curses.A_BOLD)



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

TIMER_LABELS = ["HH", "MM", "SS"]
TIMER_LIMITS = [99, 59, 59]


def start_timer(values):
    """Spustí StickyTimer (termdown v kitty) s aktuálně nastaveným h/m/s.
    Vrací True když se opravdu odpálil (total > 0), jinak False."""
    total = values[0] * 3600 + values[1] * 60 + values[2]
    if total <= 0:
        return False
    subprocess.Popen(["swaymsg", "exec",
        f"kitty --class StickyTimer --override font_size=30 -e termdown {total}"])
    return True


# ---------- connectivity: pinnuté WiFi/BT boxíky nad power menu ----------

_status_cache = {"wifi": (None, 0.0), "bt": (None, 0.0)}
_STATUS_CACHE_TTL = 2  # sekundy - stejný princip jako u _wifi_preview_cache níž,
                        # ať se daemon nedotazuje 3x/s při 300ms refresh tiku


def _cached_query_daemon(kind):
    data, ts = _status_cache[kind]
    now = time.time()
    if now - ts < _STATUS_CACHE_TTL:
        return data
    data = query_daemon(kind)
    _status_cache[kind] = (data, now)
    return data


def get_wifi_info():
    return _cached_query_daemon("wifi")


def get_bt_info():
    return _cached_query_daemon("bt")


def wifi_dbm_to_percent(dbm):
    """Standardní odhad kvality signálu z dBm (stejná formule jako NetworkManager)."""
    try:
        pct = 2 * (int(dbm) + 100)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, pct))


BT_DEVICE_MAC = "1C:6E:4C:9C:D0:41"  # MAJOR IV sluchátka

# Stav posledního pokusu o připojení - dřív se chyby prostě zahodily
# (bare except: pass), takže "nic se nestalo" bylo doslova pravda - žádná
# zpětná vazba, i když connect selhal. Teď se stav ukazuje přímo v boxíku.
CONN_BOX_H = 3
CONN_STATUS_TTL = 6  # sekund, jak dlouho zůstane ok/error zobrazené než zmizí
_wifi_conn_state = {"status": "idle", "msg": "", "ts": 0.0}
_bt_conn_state = {"status": "idle", "msg": "", "ts": 0.0}


def _conn_status_line(state):
    """Vrátí (status, msg) k zobrazení, nebo (None, None) když není co hlásit
    (idle, nebo ok/error co už vypršelo)."""
    if state["status"] == "connecting":
        return state["status"], state["msg"]
    if state["status"] in ("ok", "error") and time.time() - state["ts"] < CONN_STATUS_TTL:
        return state["status"], state["msg"]
    return None, None


def _last_line(text):
    lines = [l.strip() for l in _strip_ansi(text).strip().splitlines() if l.strip()]
    return lines[-1] if lines else "failed"


def connect_bluetooth_device(mac):
    """Připojí konkrétní BT zařízení na pozadí, dashboard zůstává otevřený -
    stav (baterie/connected tečka) se dotáhne sám při dalším refreshi daemona.
    Výsledek (ok/error + hlášku z bluetoothctl) hlásí do _bt_conn_state."""
    _bt_conn_state.update(status="connecting", msg="connecting…", ts=time.time())

    def worker():
        try:
            r = subprocess.run(["bluetoothctl", "connect", mac], timeout=10,
                                capture_output=True, text=True)
            if r.returncode == 0:
                _bt_conn_state.update(status="ok", msg="connected", ts=time.time())
            else:
                _bt_conn_state.update(status="error",
                                       msg=_last_line(r.stdout + r.stderr)[:40], ts=time.time())
        except Exception as e:
            _bt_conn_state.update(status="error", msg=str(e)[:40], ts=time.time())
    threading.Thread(target=worker, daemon=True).start()


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text):
    """iwctl barví výstup i když neběží v tty (přes subprocess), takže řádky
    obsahují escape sekvence jako '\\x1b[90m'. Bez odstranění to rozbije
    detekci oddělovacího řádku ('----') - ten pak nezačíná na '-' ale na
    escape kód, propadne filtrem a naparsuje se jako neplatný název sítě."""
    return _ANSI_RE.sub("", text)


def _parse_iwctl_network_column(line):
    """iwctl tabulky mají sloupce oddělené 2+ mezerami. Aktuálně připojená síť
    má navíc prefix '>' - ten musí pryč PŘED splitem, jinak se '>' sám stane
    prvním 'sloupcem' (protože za ním jsou taky 2+ mezery kvůli zarovnání)."""
    line = line.strip()
    if line.startswith(">"):
        line = line[1:].strip()
    parts = re.split(r"\s{2,}", line)
    if not parts or not parts[0]:
        return None
    return parts[0].strip()


def get_available_wifi_networks():
    """Seznam SSID z posledního skenu, v pořadí jak je iwctl vrací (běžně dle síly signálu)."""
    try:
        r = subprocess.run(["iwctl", "station", "wlan0", "get-networks"],
                            capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    names = []
    for line in _strip_ansi(r.stdout).split("\n"):
        line = line.strip()
        if not line or line.startswith("-") or "Network name" in line or "Available" in line:
            continue
        name = _parse_iwctl_network_column(line)
        if name:
            names.append(name)
    return names


def get_known_wifi_networks():
    try:
        r = subprocess.run(["iwctl", "known-networks", "list"],
                            capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    names = []
    for line in _strip_ansi(r.stdout).split("\n"):
        line = line.strip()
        if not line or line.startswith("-") or line.startswith("Name") or "Known Networks" in line:
            continue
        name = _parse_iwctl_network_column(line)
        if name:
            names.append(name)
    return names


_wifi_preview_cache = {"ssid": None, "ts": 0.0}


def get_best_known_available_wifi():
    """Nejsilnější dostupná known síť BEZ spouštění nového skenu (čte jen
    poslední výsledky iwctl, je to rychlé) - používá se pro živý náhled
    v boxíku. Krátce cachováno (2s), ať se subprocess netočí při každém
    překreslení."""
    now = time.time()
    if now - _wifi_preview_cache["ts"] < 2:
        return _wifi_preview_cache["ssid"]
    available = get_available_wifi_networks()
    known = set(get_known_wifi_networks())
    best = next((s for s in available if s in known), None)
    _wifi_preview_cache["ssid"] = best
    _wifi_preview_cache["ts"] = now
    return best


def connect_best_known_wifi(ssid=None):
    """Připojí danou síť (pokud známe z náhledu) hned, jinak jako fallback
    Scan -> najde průnik dostupných a known sítí -> připojí první shodu
    (iwctl řadí get-networks zhruba podle síly signálu, takže první shoda
    by měla být nejsilnější dostupná known síť). Běží na pozadí.
    Výsledek (ok/error + hlášku z iwctl) hlásí do _wifi_conn_state, takže
    "nic se nestalo" po Enteru je teď vidět proč - selhání se dřív tiše
    zahazovalo (bare except: pass)."""
    _wifi_conn_state.update(status="connecting",
                             msg=f"connecting {ssid}…" if ssid else "scanning…", ts=time.time())

    def worker():
        try:
            target = ssid
            if not target:
                subprocess.run(["iwctl", "station", "wlan0", "scan"], timeout=10,
                                capture_output=True)
                time.sleep(2)  # dát skenu chvíli, ať se stihne naplnit
                available = get_available_wifi_networks()
                known = set(get_known_wifi_networks())
                target = next((s for s in available if s in known), None)
            if not target:
                _wifi_conn_state.update(status="error", msg="no known network in range", ts=time.time())
                return
            _wifi_conn_state.update(status="connecting", msg=f"connecting {target}…", ts=time.time())
            r = subprocess.run(["iwctl", "station", "wlan0", "connect", target],
                                timeout=15, capture_output=True, text=True)
            if r.returncode == 0:
                _wifi_conn_state.update(status="ok", msg=f"connected {target}", ts=time.time())
            else:
                _wifi_conn_state.update(status="error",
                                         msg=_last_line(r.stdout + r.stderr)[:40], ts=time.time())
        except Exception as e:
            _wifi_conn_state.update(status="error", msg=str(e)[:40], ts=time.time())
    threading.Thread(target=worker, daemon=True).start()


# ---------- pravý panel: app launcher (render + vlastní smyčka) ----------

def filter_apps(apps, query):
    if not query:
        return apps
    q = query.lower()
    return [a for a in apps if q in a[0].lower()]


def draw_matched(stdscr, y, x, text, query, max_w, base_style, match_style):
    """Vykreslí text, se zvýrazněnou první shodou query (case-insensitive) -
    hned je vidět PROČ se výsledek zrovna zobrazil, místo holého výpisu."""
    text = text[:max_w]
    idx = text.lower().find(query.lower()) if query else -1
    if idx == -1:
        safe_addstr(stdscr, y, x, text, base_style)
        return
    safe_addstr(stdscr, y, x, text[:idx], base_style)
    safe_addstr(stdscr, y, x + idx, text[idx:idx + len(query)], match_style)
    safe_addstr(stdscr, y, x + idx + len(query), text[idx + len(query):], base_style)


# ---------- sidebar ----------

def draw_sidebar(stdscr, items, selected, y0, x0, width, height, power_start,
                  timer_values, timer_field,
                  launcher_active, launcher_query, launcher_results, launcher_sel,
                  focused=True):
    draw_box(stdscr, y0, x0, height, width, focused)

    power_block_h = len(POWER_OPTIONS) + 2
    conn_block_h = 3 * CONN_BOX_H + 1  # Timer + WiFi + BT boxy + 1 řádek odděleného odstupu
    content_h = height - 2 - power_block_h - conn_block_h

    ws_items = [(i, it) for i, it in enumerate(items) if it[1] == "workspace"]

    if launcher_active:
        # Launcher normálně vůbec není vidět - objeví se jen dokud se píše,
        # a Workspaces mu ustoupí do zbylého prostoru dole.
        band_h = max(content_h // 2, 5)
        band1_y = y0 + 1
        ws_y = band1_y + band_h
        ws_visible = content_h - band_h - 1

        safe_addstr(stdscr, band1_y, x0 + 2, "── Launcher ──"[:width - 4], curses.color_pair(6))
        safe_addstr(stdscr, band1_y + 1, x0 + 2, f"> {launcher_query}"[:width - 4].ljust(width - 4),
                    curses.color_pair(3) | curses.A_BOLD)
        if launcher_results:
            for n, (name, _cmd) in enumerate(launcher_results[:band_h - 3]):
                row = band1_y + 2 + n
                style = curses.color_pair(3) | curses.A_REVERSE if n == launcher_sel else curses.color_pair(1)
                match_style = style if n == launcher_sel else curses.color_pair(4) | curses.A_BOLD
                draw_matched(stdscr, row, x0 + 2, name, launcher_query, width - 4, style, match_style)
        else:
            safe_addstr(stdscr, band1_y + 2, x0 + 2, "(no match)", curses.color_pair(5))
    else:
        ws_y = y0 + 1
        ws_visible = content_h - 1

    # --- Workspace switcher - vždy vidět, scroll podle výběru ---
    safe_addstr(stdscr, ws_y, x0 + 2, "── Workspaces ──"[:width - 4], curses.color_pair(6))
    sel_local = next((n for n, (i, _it) in enumerate(ws_items) if i == selected), None)
    offset = 0
    if sel_local is not None and len(ws_items) > ws_visible:
        offset = max(0, min(sel_local - ws_visible // 2, len(ws_items) - ws_visible))
    for n, (i, (name, _kind, extra)) in enumerate(ws_items[offset:offset + ws_visible]):
        row = ws_y + 1 + n
        label = f"{name}{extra}"
        style = curses.color_pair(3) | curses.A_REVERSE if i == selected else curses.color_pair(1)
        safe_addstr(stdscr, row, x0 + 2, label[:width - 4].ljust(width - 4), style)
    if not ws_items:
        safe_addstr(stdscr, ws_y + 1, x0 + 2, "(no workspaces)", curses.color_pair(6))

    # --- pinnuté Timer/WiFi/BT boxíky, hned nad PowerMenu ---
    power_y = y0 + height - 1 - len(POWER_OPTIONS)
    timer_idx = next((i for i, it in enumerate(items) if it[1] == "timer"), None)
    wifi_idx = next((i for i, it in enumerate(items) if it[1] == "wifi"), None)
    bt_idx = next((i for i, it in enumerate(items) if it[1] == "bt"), None)

    bt_box_y = power_y - 1 - CONN_BOX_H
    wifi_box_y = bt_box_y - CONN_BOX_H
    timer_box_y = wifi_box_y - CONN_BOX_H

    def _status_color(status):
        if status == "connecting":
            return curses.color_pair(2) | curses.A_BOLD  # yellow
        if status == "ok":
            return curses.color_pair(4) | curses.A_BOLD  # green
        return curses.color_pair(5) | curses.A_BOLD       # red (error)

    def _status_dot(status):
        return {"connecting": "◌", "ok": "●", "error": "✕"}.get(status, "●")

    timer_focused = selected == timer_idx
    draw_box(stdscr, timer_box_y, x0, CONN_BOX_H, width, timer_focused, "Timer")
    x = x0 + 2
    for i, (val, label) in enumerate(zip(timer_values, TIMER_LABELS)):
        style = curses.color_pair(3) | curses.A_REVERSE if (timer_focused and i == timer_field) \
            else curses.color_pair(1) | curses.A_BOLD
        safe_addstr(stdscr, timer_box_y + 1, x, f"{val:02d}", style)
        x += 2
        if i < 2:
            safe_addstr(stdscr, timer_box_y + 1, x, ":", curses.color_pair(6))
            x += 1
    if timer_focused:
        hint = "  Enter: start"
        safe_addstr(stdscr, timer_box_y + 1, x, hint[:max(width - 4 - (x - x0 - 2), 0)],
                    curses.color_pair(6))


    wifi_focused = selected == wifi_idx
    wifi_data = get_wifi_info()
    draw_box(stdscr, wifi_box_y, x0, CONN_BOX_H, width, wifi_focused, "WiFi")
    wifi_status, wifi_msg = _conn_status_line(_wifi_conn_state)
    if wifi_status:
        line = f"{_status_dot(wifi_status)} {wifi_msg}"
        safe_addstr(stdscr, wifi_box_y + 1, x0 + 2, line[:width - 4], _status_color(wifi_status))
    else:
        if wifi_data:
            pct = wifi_dbm_to_percent(wifi_data.get("rssi"))
            base = f"● {pct}%" if pct is not None else "● ?"
            base_color = curses.color_pair(4) | curses.A_BOLD
        else:
            base = "○ --"
            base_color = curses.color_pair(5)
        if wifi_focused:
            wifi_hint_ssid = get_best_known_available_wifi()
            hint = f"connect {wifi_hint_ssid}" if wifi_hint_ssid else "connect best known"
            safe_addstr(stdscr, wifi_box_y + 1, x0 + 2, base, base_color)
            safe_addstr(stdscr, wifi_box_y + 1, x0 + 2 + len(base) + 2,
                        hint[:max(width - 4 - len(base) - 2, 0)], curses.color_pair(6))
        else:
            safe_addstr(stdscr, wifi_box_y + 1, x0 + 2, base, base_color)

    bt_focused = selected == bt_idx
    bt_data = get_bt_info()
    draw_box(stdscr, bt_box_y, x0, CONN_BOX_H, width, bt_focused, "Bluetooth")
    bt_status, bt_msg = _conn_status_line(_bt_conn_state)
    if bt_status:
        line = f"{_status_dot(bt_status)} {bt_msg}"
        safe_addstr(stdscr, bt_box_y + 1, x0 + 2, line[:width - 4], _status_color(bt_status))
    else:
        if bt_data:
            bat_str = bt_data.get("battery") or "--"
            base = f"● {bat_str}"
            base_color = curses.color_pair(4) | curses.A_BOLD
        else:
            base = "○ --"
            base_color = curses.color_pair(5)
        if bt_focused:
            hint = "connect MAJOR IV"
            safe_addstr(stdscr, bt_box_y + 1, x0 + 2, base, base_color)
            safe_addstr(stdscr, bt_box_y + 1, x0 + 2 + len(base) + 2,
                        hint[:max(width - 4 - len(base) - 2, 0)], curses.color_pair(6))
        else:
            safe_addstr(stdscr, bt_box_y + 1, x0 + 2, base, base_color)

    # --- pinnuté PowerMenu, beze změny ---
    safe_addstr(stdscr, power_y - 1, x0 + 2, "─" * (width - 4), curses.color_pair(6))
    for j, (key, name, _cmd) in enumerate(POWER_OPTIONS):
        idx = power_start + j
        label = f"[^{key}] {name}"
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
    stdscr.timeout(300)  # non-blocking getch -> dashboard se sám překresluje
                          # i bez stisku klávesy (WiFi signál / BT baterie
                          # a stav se doťáhnou téměř okamžitě po Enteru)

    workspaces = get_workspaces()

    sidebar_items = [(ws["name"], "workspace", "") for ws in sorted(workspaces, key=lambda w: w["num"])]
    sidebar_items += [
        ("Timer", "timer", ""),
        ("WiFi", "wifi", ""),
        ("Bluetooth", "bt", ""),
    ]
    power_start = len(sidebar_items)
    for key, name, _cmd in POWER_OPTIONS:
        sidebar_items.append((name, "power", ""))

    sel_side = 0
    power_keys = {ctrl(k): cmd for k, _n, cmd in POWER_OPTIONS}
    CALENDAR_KEY = ctrl("K")  # ne Ctrl+C - to je SIGINT, terminál by to sežral dřív než curses

    all_apps = scan_desktop_apps()
    timer_values = [0, 0, 0]
    timer_field = 0
    WEATHER_STRIP_H = 12  # o další řádek víc

    # Launcher normálně vůbec není vidět - žádná položka v sidebar_items,
    # žádné Tab cyklení. Objeví se, jakmile se začne psát cokoliv
    # tisknutelného (viz "start typing" větev níž), kdekoliv v dashboardu.
    launcher_active = False
    launcher_query = ""
    launcher_sel = 0

    while True:
        stdscr.erase()  # ne clear() - to force-touchne celé okno a zbytečně bliká
        h, w = stdscr.getmaxyx()
        side_w = max(w // 5, 20)
        cx0, cy0 = side_w + 1, 1
        cwidth = (w - side_w) - 2
        cheight = (h - 1) - WEATHER_STRIP_H
        strip_y = cy0 + cheight
        cal_w = (cwidth - 1) * 2 // 5  # poměr 2:3 kalendář:weather
        weather_x = cx0 + cal_w + 1
        weather_w = cwidth - cal_w - 1

        launcher_results = filter_apps(all_apps, launcher_query) if launcher_active else []
        if launcher_sel >= len(launcher_results):
            launcher_sel = max(len(launcher_results) - 1, 0)

        # h (ne h-1) - žádný rezervovaný spodní řádek. draw_box je zabalený
        # v try/except curses.error, takže i kdyby psaní do úplně posledního
        # rohu obrazovky narazilo na starou ncurses libůstku (addch do
        # pravého dolního rohu okna může shodit error), nic to nerozbije -
        # nanejvýš by se ten jeden roh nedokreslil.
        draw_sidebar(stdscr, sidebar_items, sel_side, 0, 0, side_w, h, power_start,
                     timer_values, timer_field,
                     launcher_active, launcher_query, launcher_results, launcher_sel, focused=True)
        draw_box(stdscr, 0, side_w, h, w - side_w, False)
        today = datetime.date.today()
        render_calendar_strip(stdscr, today.year, today.month, today.day, load_notes_cached(),
                               strip_y, cx0, cal_w, WEATHER_STRIP_H)
        draw_weather_strip(stdscr, strip_y, weather_x, weather_w, WEATHER_STRIP_H)

        name, kind, _extra = sidebar_items[sel_side]
        pending_thumbs = []
        if kind == "workspace":
            ws = next((w for w in workspaces if w["name"] == name), None)
            pending_thumbs = draw_workspace_preview(stdscr, ws, cy0, cx0, cwidth, cheight)
        elif kind in ("wifi", "bt", "timer"):
            pass  # stav a ovládání se teď dějí přímo v pinnutém boxíku v sidebaru
        elif kind == "power":
            draw_power_preview(stdscr, name, cy0, cx0, cwidth, cheight)

        stdscr.refresh()
        # AŽ TEĎ, mimo curses - viz komentář u render_kitty_thumbnails() výš
        render_kitty_thumbnails(pending_thumbs)
        key = stdscr.getch()

        # globální zkratky - fungují odkudkoliv v hlavní smyčce.
        # PowerMenu + Calendar jedou přes Ctrl (control-kódy 1-26 nejsou
        # tisknutelné znaky, takže nikdy nekolidují s psaním do AppLauncheru,
        # ani Shift). Calendar je na Ctrl+K, ne Ctrl+C - Ctrl+C je SIGINT a
        # terminál by ho sežral dřív, než by se vůbec dostal do getch().
        if key in power_keys:
            close_self()
            _kitty_clear_placements()
            subprocess.Popen(power_keys[key], start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if key == CALENDAR_KEY:
            draw_sidebar(stdscr, sidebar_items, sel_side, 0, 0, side_w, h, power_start,
                         timer_values, timer_field,
                         launcher_active, launcher_query, launcher_results, launcher_sel, focused=False)
            draw_box(stdscr, 0, side_w, h, w - side_w, True)
            stdscr.refresh()
            _kitty_clear_placements()  # run_calendar má vlastní smyčku - hlavní tik, co jinak čistí staré thumbnaily, se dokud běží vůbec nezavolá
            run_calendar(stdscr, cy0, cx0, cwidth, cheight)
            continue

        # "start typing" - libovolné tisknutelné písmeno kdekoliv v dashboardu
        # otevře launcher (dmenu/rofi styl). Rozsah 32-126 nikdy nekoliduje
        # s Ctrl kódy (1-26) ani s Tab/Enter/Esc (9/10/13/27).
        if not launcher_active and 32 <= key <= 126:
            launcher_active = True
            launcher_query = chr(key)
            launcher_sel = 0
            continue

        if launcher_active:
            if key == 27:
                launcher_active = False
                launcher_query = ""
            elif key == ord('\t'):
                launcher_active = False  # Tab = "pryč z hledání", ne skok jinam ve stejném stisku
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if launcher_query:
                    launcher_query = launcher_query[:-1]
                    launcher_sel = 0
                else:
                    launcher_active = False
            elif key == curses.KEY_UP:
                launcher_sel = max(launcher_sel - 1, 0)
            elif key == curses.KEY_DOWN:
                launcher_sel = min(launcher_sel + 1, max(len(launcher_results) - 1, 0))
            elif key in (10, 13):
                if launcher_results:
                    cmd = launcher_results[launcher_sel][1]
                    close_self()
                    _kitty_clear_placements()
                    subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
            elif 32 <= key <= 126:
                launcher_query += chr(key)
                launcher_sel = 0
            continue

        name, kind, _extra = sidebar_items[sel_side]

        if key == 27:
            close_self()
            _kitty_clear_placements()
            return
        elif key == ord('\t'):
            sel_side = (sel_side + 1) % len(sidebar_items)
        elif key == curses.KEY_BTAB:
            sel_side = (sel_side - 1) % len(sidebar_items)
        elif kind == "timer" and key == curses.KEY_LEFT:
            timer_field = (timer_field - 1) % 3
        elif kind == "timer" and key == curses.KEY_RIGHT:
            timer_field = (timer_field + 1) % 3
        elif kind == "timer" and key == curses.KEY_UP:
            timer_values[timer_field] = (timer_values[timer_field] + 1) % (TIMER_LIMITS[timer_field] + 1)
        elif kind == "timer" and key == curses.KEY_DOWN:
            timer_values[timer_field] = (timer_values[timer_field] - 1) % (TIMER_LIMITS[timer_field] + 1)
        elif key in (10, 13):
            if kind == "workspace":
                ws = next((w for w in workspaces if w["name"] == name), None)
                if ws:
                    close_self()
                    _kitty_clear_placements()
                    switch_workspace(ws["num"])
                    return
            elif kind == "timer":
                if start_timer(timer_values):
                    close_self()
                    _kitty_clear_placements()
                    return
            elif kind == "wifi":
                connect_best_known_wifi(get_best_known_available_wifi())
            elif kind == "bt":
                connect_bluetooth_device(BT_DEVICE_MAC)
            elif kind == "power":
                for _k, name_, cmd_ in POWER_OPTIONS:
                    if name_ == name:
                        close_self()
                        _kitty_clear_placements()
                        subprocess.Popen(cmd_, start_new_session=True,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return


if __name__ == "__main__":
    curses.wrapper(main)
