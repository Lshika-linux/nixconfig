#!/usr/bin/env python3
"""
swcc_dashboard.py - fullscreen system controlcenter (Win+Tab).

Layout:
  - Left sidebar (~1/5 width): workspace boxes 1-10 (always all of them,
    empty ones included), then pinned Timer/WiFi/Bluetooth boxes, then
    pinned PowerMenu at the bottom.
  - Launcher: a strip pinned to the top of the content area. Hidden/idle
    until you start typing, then it fuzzy-searches installed apps.
  - Main content area: a live preview of whichever workspace is currently
    Tab-selected in the sidebar, or a PowerMenu preview.
  - Bottom strip: Calendar (passive month view) + Weather, always visible.
  - Right column: vertical Volume/Brightness bars.

Workspace preview is reconstructed straight from `swaymsg -t get_tree`
(see get_workspace_layout / draw_workspace_tile) - no screenshots, no
external daemon. This means it works even for a workspace that isn't
currently visible on screen, and it's always in sync with reality.

Calendar is NOT part of Tab-cycling - it's just the passive strip at the
bottom, plus Ctrl+K anywhere opens an interactive fullscreen overlay
(run_calendar).

Timer is a pinned box (like WiFi/BT): h:m:s is set with arrow keys while
the box is Tab-selected, Enter starts a StickyTimer (termdown in kitty)
and closes the dashboard.

Connectivity (WiFi/BT) is a pinned box (like Timer): it shows live status
(SSID/signal, paired device/battery) and, on Enter, connects to the
strongest known network or the configured BT_DEVICE_MAC in a background
thread (see connect_best_known_wifi / connect_bluetooth_device) - no
interactive TUI, no second kitty pane, just iwctl/bluetoothctl calls with
the result reported back into the box. For anything beyond that quick
connect (picking a different network, pairing a new device), Ctrl+W /
Ctrl+B close the dashboard and open impala / bluetuith in a real floating
kitty window (see open_wifi_manager / open_bt_manager).

PowerMenu can be triggered from anywhere in the dashboard via Ctrl+L/O/R/P,
and is also part of Tab-cycling as pinned items at the bottom of the sidebar.
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

from swcc_common import query_daemon

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, "scripts_sway")
NOTES_FILE = os.path.expanduser("~/.local/share/calendar_notes.json")

WS_COUNT = 10  # sway workspaces 1-10 - the sidebar ALWAYS shows all of them, even empty ones

# Cockpit's own windows - excluded when figuring out "what's running on this
# workspace", otherwise the workspace the dashboard is currently open on
# would tautologically report "CockpitDashboard" instead of the real
# content underneath it.
CC_OWN_APP_IDS = {
    "SwayControlCenter", "WindowSwitcher", "Connectivity", "Weather",
    "TimerPicker", "StickyTimer", "Calendar", "PowerMenu", "AppLauncher",
    "FloatingCenter",
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


def ctrl(letter):
    """Key code getch() returns for Ctrl+letter (1-26, non-printable - never
    collides with normal typing, unlike Shift)."""
    return ord(letter.upper()) - 64


POWER_OPTIONS = [
    ("L", "Lock", ["bash", os.path.join(SCRIPTS, "lock.sh")]),
    ("O", "Logout", ["swaymsg", "exit"]),
    ("R", "Reboot", ["systemctl", "reboot"]),
    ("P", "Shutdown", ["systemctl", "poweroff"]),
]

# Plain unicode emoji so this works without depending on a nerd font.
# Swap these out if you'd rather use nerd-font glyphs (matches connectivity.py's style).
POWER_ICONS = {
    "Lock": "🔒",
    "Logout": "🚪",
    "Reboot": "🔁",
    "Shutdown": "⏻",
}


def draw_power_preview(stdscr, name, y0, x0, width, height):
    """Large icon + oversized heading - curses can't scale fonts, so
    'large' means a bold glyph, extra spacing, and letters spread out."""
    icon = POWER_ICONS.get(name, "?")
    danger = name in ("Shutdown", "Reboot", "Logout")
    color = (curses.color_pair(5) if danger else curses.color_pair(3)) | curses.A_BOLD

    cy = y0 + height // 2 - 2
    safe_addstr(stdscr, cy, x0 + width // 2 - 1, icon, color)

    label = " ".join(name.upper())
    safe_addstr(stdscr, cy + 3, x0 + width // 2 - len(label) // 2, label, color)

    shortcut = next((k for k, n, _c in POWER_OPTIONS if n == name), "?")
    hint = f"Enter or [^{shortcut}] to confirm"
    safe_addstr(stdscr, y0 + height - 1, x0 + width // 2 - len(hint) // 2, hint, curses.color_pair(2))


# ---------- weather (from weather.py) ----------

def weather_icon(desc):
    """The VS16 selector (\ufe0f) at the end requests the emoji presentation
    form instead of the text form - PowerMenu's plain emoji (🔒💤🚪) already
    render fine, so this should give bigger/more colorful icons than the
    thin text glyphs (☀ without VS16). Risk: if the font/kitty has no color
    emoji fallback, this can show a tofu box instead, or make the icon two
    cells wide and throw off alignment between adjacent rows - if that
    happens, drop the \ufe0f and go back to plain text glyphs."""
    desc = desc.lower()
    if "thunder" in desc:
        return "⛈️"
    if "snow" in desc:
        return "❄️"
    if "rain" in desc or "drizzle" in desc:
        return "🌧️"
    if "cloud" in desc or "overcast" in desc:
        return "☁️"
    if "fog" in desc or "mist" in desc:
        return "🌫️"
    if "sunny" in desc or "clear" in desc:
        return "☀️"
    if "partly" in desc:
        return "⛅"
    return "~"


# ---------- sway tree / running apps ----------

def get_workspaces():
    """`swaymsg -t get_workspaces` returns num/name/rect/focused/visible/
    output directly - no need to walk the tree ourselves."""
    try:
        r = subprocess.run(["swaymsg", "-t", "get_workspaces"],
                            capture_output=True, text=True, timeout=2)
        return json.loads(r.stdout)
    except Exception:
        return []


def switch_workspace(num):
    subprocess.run(["swaymsg", "workspace", "number", str(num)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _get_leaf_con_ids():
    """Sway con ids of every window (leaf nodes with a real app_id/class)
    in the whole tree - used to diff "what's new" after launching an app
    from the launcher."""
    try:
        r = subprocess.run(["swaymsg", "-t", "get_tree"],
                            capture_output=True, text=True, timeout=2)
        tree = json.loads(r.stdout)
    except Exception:
        return set()
    ids = set()

    def walk(node):
        is_window = not node.get("nodes") and not node.get("floating_nodes") and (
            node.get("app_id") or (node.get("window_properties") or {}).get("class"))
        if is_window and node.get("id") is not None:
            ids.add(node["id"])
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child)

    walk(tree)
    return ids


_claimed_con_ids = set()
_claim_lock = threading.Lock()


def launch_app_on_workspace(cmd, target_num=None):
    """Launches an app from the launcher WITHOUT stealing focus away from
    the dashboard - no close_self(), the dashboard stays fullscreen and
    visible exactly as it was (the app physically launches on whichever
    workspace Sway currently has focused, i.e. the dashboard's own
    workspace). If target_num is given, a background thread quietly moves
    it there via `move to workspace number N` - unlike `workspace number N`,
    `move` does NOT change focus, so the dashboard never gets displaced."""
    before = _get_leaf_con_ids() if target_num is not None else None

    subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if target_num is None:
        return

    def worker():
        for _ in range(30):  # ~6s at a 0.2s step - enough even for slower-starting apps (Electron etc.)
            time.sleep(0.2)
            now = _get_leaf_con_ids()
            with _claim_lock:
                new_ids = (now - before) - _claimed_con_ids
                if new_ids:
                    con_id = next(iter(new_ids))
                    _claimed_con_ids.add(con_id)
                    subprocess.run(
                        ["swaymsg", f"[con_id={con_id}] move to workspace number {target_num}"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return

    threading.Thread(target=worker, daemon=True).start()


# ---------- condensing window titles for the sidebar list ----------
#
# The window title (node["name"] from the sway tree) carries the
# interesting bit, but differently per app: a terminal's title is a
# path/running command (we want that in full), a browser's title is
# "<page> - <site>" (we only want the site, ideally as a domain), and most
# other apps have "<document> - <something> - <app name + version>" (we
# only want that first segment - we already know it's Obsidian from app_id).

TERMINAL_APPS = {"kitty", "alacritty", "foot", "wezterm", "st", "urxvt", "xterm", "ghostty"}
BROWSER_APPS = {"librewolf", "firefox", "chromium", "chrome", "google-chrome",
                 "brave-browser", "zen", "qutebrowser", "vivaldi"}
# browser names as they appear IN THE TITLE (not the app_id) - to strip out
BROWSER_TITLE_NAMES = {"librewolf", "mozilla firefox", "firefox", "chromium",
                        "google chrome", "brave", "zen browser", "vivaldi"}

# known sites -> domain. The title only carries the site's display name
# ("Claude"), we never get the actual URL from the sway tree, so this is
# just a manual remap to whatever you'd rather see instead.
SITE_DOMAINS = {
    "claude": "claude.ai",
    "chatgpt": "chatgpt.com",
    "youtube": "youtube.com",
    "github": "github.com",
    "gitlab": "gitlab.com",
    "reddit": "reddit.com",
    "gmail": "mail.google.com",
    "stack overflow": "stackoverflow.com",
    "wikipedia": "wikipedia.org",
    "nixos search": "search.nixos.org",
    "mynixos": "mynixos.com",
    "seznam.cz": "seznam.cz",
    "proton mail": "mail.proton.me",
    "proton calendar": "calendar.proton.me",
    "messenger": "messenger.com",
    "facebook": "facebook.com",
}

_TITLE_SPLIT_RE = re.compile(r"\s+[-—–|]\s+")


def condense_title(app, title):
    """Returns a condensed window title - only the part that actually adds
    information beyond the app's own name. Empty string = nothing useful
    to show."""
    app_l = (app or "").lower()
    title = (title or "").strip()
    if not title:
        return ""

    if app_l in TERMINAL_APPS:
        return title  # the path / running command is exactly what we want

    parts = [p.strip() for p in _TITLE_SPLIT_RE.split(title) if p.strip()]
    if not parts:
        return title

    if app_l in BROWSER_APPS:
        # the last segment is the site name ("... - Claude"), drop the browser name
        segs = [p for p in parts if p.lower() not in BROWSER_TITLE_NAMES] or parts
        site = segs[-1]
        return SITE_DOMAINS.get(site.lower(), site)

    # any other app: first segment (document/vault name), the rest is the app name + version
    first = parts[0]
    if first.lower() == app_l:
        return ""  # title is just the app's own name - nothing new to show
    return first


def _node_window_name(node):
    """App name for a leaf window (app_id, falling back to
    window_properties.class for xwayland apps that don't set app_id), or
    None if this node isn't a leaf window."""
    if node.get("nodes") or node.get("floating_nodes"):
        return None
    return node.get("app_id") or (node.get("window_properties") or {}).get("class")


def _is_cc_subtree(node):
    """True if this subtree contains NO windows other than cockpit's own -
    such a node gets dropped entirely when reconstructing the layout (see
    _layout_node)."""
    name = _node_window_name(node)
    if name is not None:
        return name in CC_OWN_APP_IDS
    children = node.get("nodes", []) + node.get("floating_nodes", [])
    if not children:
        return True
    return all(_is_cc_subtree(c) for c in children)


def _layout_node(node, x, y, w, h, out):
    """Reconstructs the layout from the STRUCTURE of the sway tree into
    normalized 0..1 coordinates, instead of from absolute rects.

    This is what elegantly handles the fact that the commandcenter
    itself is just another sibling in a tiling split (fullscreen is a
    display mode, not a layout change), so it keeps holding its slot even
    once we filter it out of the listing. Instead of patching absolute
    coordinates after the fact, we just DROP that node and redistribute its
    share across the remaining siblings proportionally to their size -
    exactly what sway would do if that window were closed. The result is
    consistent no matter where in the split cc sat, or whether it's
    even present on that workspace at all."""
    name = _node_window_name(node)
    if name is not None:
        if name not in CC_OWN_APP_IDS:
            out.append({"name": name, "title": node.get("name") or "", "n": (x, y, w, h)})
        return

    tiling = [c for c in node.get("nodes", []) if not _is_cc_subtree(c)]
    floating = [c for c in node.get("floating_nodes", []) if not _is_cc_subtree(c)]

    if tiling:
        layout = node.get("layout", "splith")
        if layout in ("tabbed", "stacked"):
            # sway only shows one tab at a time - pick the focused one (the
            # first id in the focus list), so the preview doesn't draw
            # several windows stacked on top of each other
            focus = node.get("focus") or []
            if focus:
                chosen = next((c for c in tiling if c.get("id") == focus[0]), tiling[0])
            else:
                chosen = tiling[0]
            _layout_node(chosen, x, y, w, h, out)
        else:
            horiz = layout == "splith"
            key = "width" if horiz else "height"
            weights = [max(c.get("rect", {}).get(key, 0), 1) for c in tiling]
            total = sum(weights)
            pos = x if horiz else y
            for child, weight in zip(tiling, weights):
                share = (w if horiz else h) * weight / total
                if horiz:
                    _layout_node(child, pos, y, share, h, out)
                else:
                    _layout_node(child, x, pos, w, share, out)
                pos += share

    # floating windows aren't part of the split - they keep their own
    # position, so they're normalized directly against the workspace rect
    # (see get_workspace_layout)
    for child in floating:
        _layout_node(child, x, y, w, h, out)


def get_workspace_layout():
    """Walks the ENTIRE sway tree once (get_tree) and returns
    {ws_num: {"aspect": (w, h), "windows": [{"name", "n": (x,y,w,h)}, ...]}},
    where "n" is NORMALIZED 0..1 coordinates within the workspace, computed
    by reconstructing the split tree (see _layout_node) - not from absolute
    rects.

    No screenshots, no grim - this works just as well for a workspace
    that's not currently visible, because Sway keeps computing the layout
    regardless of whether anything is actually being drawn to the screen."""
    try:
        r = subprocess.run(["swaymsg", "-t", "get_tree"],
                            capture_output=True, text=True, timeout=2)
        tree = json.loads(r.stdout)
    except Exception:
        return {}

    result = {}

    def find_workspaces(node):
        if node.get("type") == "workspace":
            try:
                num = int(node.get("num"))
            except (TypeError, ValueError):
                return
            rect = node.get("rect", {})
            windows = []
            _layout_node(node, 0.0, 0.0, 1.0, 1.0, windows)
            result[num] = {
                "aspect": (rect.get("width", 16) or 16, rect.get("height", 9) or 9),
                "windows": windows,
            }
            return
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            find_workspaces(child)

    find_workspaces(tree)
    return result


_ws_cache = {"workspaces": [], "apps": {}, "layout": {}, "ts": 0.0}
_WS_CACHE_TTL = 1.5  # seconds - same idea as the wifi/bt cache below, so
                      # get_tree/get_workspaces doesn't get hit 3x/s by the main loop's 300ms tick


def get_workspaces_cached():
    now = time.time()
    if now - _ws_cache["ts"] > _WS_CACHE_TTL:
        _ws_cache["workspaces"] = get_workspaces()
        layout = get_workspace_layout()
        _ws_cache["layout"] = layout
        _ws_cache["apps"] = {num: [(w["name"], w.get("title", "")) for w in data["windows"]]
                              for num, data in layout.items()}
        _ws_cache["ts"] = now
    return _ws_cache["workspaces"], _ws_cache["apps"], _ws_cache["layout"]


# ---------- kitty escape sequences for clearing stale image placements ----------
#
# This used to also send actual preview images (the old photographer daemon
# + render_kitty_thumbnails) - that's gone now, the workspace preview is
# purely text/box-drawing rendered from the live sway tree (see
# draw_workspace_tile below). _kitty_send/_kitty_write stick around only
# for _kitty_clear_placements() - called before closing/switching the
# dashboard, to make sure no stale placements are left over from an older
# version of the code that ran in this same kitty window.
#
# `q=2` on every command suppresses kitty's response. Without it, kitty
# would write its own APC replies into the SAME input stream that curses
# reads keys from via getch() - a real risk of corrupting keyboard input.

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
    """Proactively kills our own kitty window via swaymsg - the SAME
    mechanism swcc_toggle.sh already uses for manual closing
    (pressing Win+grave a second time), so we know it's reliable and fast.

    Why a plain `return` and letting the process exit naturally isn't
    enough: the dashboard has a `fullscreen enable` for_window rule. When
    the launcher spawns an app, sway creates it on that same workspace, but
    until the dashboard's window is physically gone, sway's
    `popup_during_fullscreen smart` (the default) may "smartly" un-fullscreen
    the dashboard and show it tiled next to the not-yet-loaded app - that
    transition is tied to when sway actually notices the window closing,
    not to when Python reaches `return`. Killing it proactively the moment
    we decide to (instead of waiting on the reactive chain of
    process-exits -> kitty-closes-window -> sway-notices) removes the
    dashboard from the screen instantly, no matter how long the app takes
    to start."""
    subprocess.run(["swaymsg", '[app_id="SwayControlCenter"] kill'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_wifi_manager():
    """Full interactive TUI for picking/forgetting networks - the pinned
    WiFi box only quick-connects to the strongest known network. Native
    kitty window, not terminal-in-terminal - same approach the old
    connectivity.py widget used."""
    subprocess.Popen(["swaymsg", "exec", "kitty --class FloatingCenter -e impala"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_bt_manager():
    """Full interactive TUI for pairing/managing devices - the pinned BT box
    only quick-connects to BT_DEVICE_MAC."""
    subprocess.Popen(["swaymsg", "exec", "kitty --class FloatingCenter -e bluetuith"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# A terminal cell is NOT square - a typical monospace font is roughly twice
# as tall as it is wide. Used when fitting content (a workspace's windows)
# into the available space, so the aspect ratio doesn't get distorted.
CELL_ASPECT = 2.0  # cell height / cell width, in "pixel" units


def _fit_aspect(avail_w, avail_h, src_w, src_h):
    """Largest (c, r) in cell units that fits within avail_w x avail_h while
    preserving the src_w:src_h aspect ratio. Also returns (offset_x,
    offset_y) to center it within the originally allotted space."""
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


# ---------- calendar (from raficalendar.py) ----------

def load_notes():
    """Returns { 'YYYY-MM-DD': [note1, note2, ...] }. Migrates the old
    format (one string per day) to a list, so existing notes don't break."""
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
    """For the passive bottom strip, which redraws every 300ms - no need to
    read the file from disk that often, notes only change inside
    run_calendar anyway."""
    now = time.time()
    if now - _notes_cache["ts"] > 2:
        _notes_cache["data"] = load_notes()
        _notes_cache["ts"] = now
    return _notes_cache["data"]


# ---------- app launcher (generic .desktop file scan) ----------

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

def draw_box(stdscr, y, x, h, w, focused, title="", corners_only=False):
    """corners_only=True draws just the four corners instead of a full frame.

    Note the per-cell protection: this used to be ONE big try/except around
    the whole box, and it only took one cell failing (a classic ncurses
    quirk - you can't write to the very last character of a window, the
    bottom-right corner) for the except to swallow everything else too, so
    the box would render as just its corners. Each addch now has its own
    guard - at most that one character fails."""
    if h < 2 or w < 2:
        return
    color = curses.color_pair(3) | curses.A_BOLD if focused else curses.color_pair(6)

    def put(cy, cx, ch):
        try:
            stdscr.addch(cy, cx, ch, color)
        except curses.error:
            pass

    if corners_only:
        # corner length - shorter for small boxes, so they don't merge into a full frame
        n = max(min(w // 6, h // 3, 4), 1)
        put(y, x, curses.ACS_ULCORNER)
        put(y, x + w - 1, curses.ACS_URCORNER)
        put(y + h - 1, x, curses.ACS_LLCORNER)
        put(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        for i in range(1, n):
            put(y, x + i, curses.ACS_HLINE)
            put(y, x + w - 1 - i, curses.ACS_HLINE)
            put(y + h - 1, x + i, curses.ACS_HLINE)
            put(y + h - 1, x + w - 1 - i, curses.ACS_HLINE)
        for i in range(1, max(n - 1, 1)):
            put(y + i, x, curses.ACS_VLINE)
            put(y + i, x + w - 1, curses.ACS_VLINE)
            put(y + h - 1 - i, x, curses.ACS_VLINE)
            put(y + h - 1 - i, x + w - 1, curses.ACS_VLINE)
    else:
        put(y, x, curses.ACS_ULCORNER)
        put(y, x + w - 1, curses.ACS_URCORNER)
        put(y + h - 1, x, curses.ACS_LLCORNER)
        put(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        for i in range(1, w - 1):
            put(y, x + i, curses.ACS_HLINE)
            put(y + h - 1, x + i, curses.ACS_HLINE)
        for i in range(1, h - 1):
            put(y + i, x, curses.ACS_VLINE)
            put(y + i, x + w - 1, curses.ACS_VLINE)

    if title:
        try:
            stdscr.addstr(y, x + 2, f" {title[:w - 4]} ", color)
        except curses.error:
            pass


def safe_addstr(stdscr, y, x, text, attr=0):
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


# ---------- right panel: workspace preview ----------
#
# Purely from live data (get_workspace_layout) - no photographer/grim/
# screenshot needed, see draw_workspace_tile below.

def draw_workspace_tile(stdscr, num, data, y0, x0, width, height, focused=False,
                         corners_only=False):
    """Draws ONE workspace (frame + the windows inside it) into the given
    rectangle - purely from live sway tree data (no screenshot, no external
    daemon). Windows arrive in NORMALIZED 0..1 coordinates (see
    get_workspace_layout / _layout_node), so this just rescales them to the
    available character cells. corners_only draws just the corners instead
    of a full frame (used for the big preview) - windows inside always get
    a full frame."""
    if width < 3 or height < 3:
        return
    draw_box(stdscr, y0, x0, height, width, focused, str(num), corners_only=corners_only)

    inner_w, inner_h = width - 2, height - 2
    windows = data.get("windows") if data else None
    if not windows or inner_w < 2 or inner_h < 2:
        if not windows and inner_w >= 5 and inner_h >= 1:
            label = "empty"
            safe_addstr(stdscr, y0 + height // 2, x0 + max((width - len(label)) // 2, 1),
                        label, curses.color_pair(6))
        return

    # fit the preview area to the same aspect ratio as the real screen
    aspect_w, aspect_h = data.get("aspect", (16, 9))
    c, r, off_x, off_y = _fit_aspect(inner_w, inner_h, aspect_w, aspect_h)
    base_x, base_y = x0 + 1 + off_x, y0 + 1 + off_y
    max_x, max_y = base_x + c, base_y + r

    # draw bigger windows first, so smaller ones (typically floating popups)
    # get drawn on top of them - we can't tell sway's real stacking order
    # from the tree, this is a reasonable approximation
    windows_by_area = sorted(windows, key=lambda win: win["n"][2] * win["n"][3], reverse=True)
    for win in windows_by_area:
        nx, ny, nw, nh = win["n"]
        wx = base_x + max(round(nx * c), 0)
        wy = base_y + max(round(ny * r), 0)

        # clamp size to at least 1 cell, then to whatever actually still
        # fits within the tile - floating windows can overflow their slot
        ww = max(round(nw * c), 1)
        ww = min(ww, max_x - wx)
        ww = max(ww, 1)
        wh = max(round(nh * r), 1)
        wh = min(wh, max_y - wy)
        wh = max(wh, 1)

        letter, color_idx = _app_icon_placeholder(win["name"])
        style = curses.color_pair(color_idx) | curses.A_BOLD

        if ww >= 3 and wh >= 2:
            draw_box(stdscr, wy, wx, wh, ww, False)
            label = win["name"][:ww - 2]
            safe_addstr(stdscr, wy + wh // 2, wx + max((ww - len(label)) // 2, 1), label, style)
        else:
            safe_addstr(stdscr, wy, wx, letter, style)


# ---------- right panel: weather ----------

def draw_weather_strip(stdscr, y0, x0, width, height):
    """Permanent compact weather block - always visible below the main
    content. Content (max 3 lines) is vertically centered in whatever
    height the box has."""
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


# ---------- right panel: volume/brightness vertical bars ----------
#
# Sits to the right of the big preview (workspace/power preview), NOT the
# full height of the right side - it ends where the preview ends, above
# the Calendar/Weather strip (which stays full-width as before).

_av_cache = {"volume": (None, 0.0), "brightness": (None, 0.0)}
_AV_CACHE_TTL = 1  # seconds - same idea as the wifi/bt cache, so
                    # pactl/brightnessctl doesn't get hit 3x/s by the main loop's 300ms tick


def _fetch_volume():
    try:
        r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                            capture_output=True, text=True, timeout=2)
        m = re.search(r"(\d+)%", r.stdout)
        if not m:
            return None
        pct = int(m.group(1))
        rm = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                             capture_output=True, text=True, timeout=2)
        muted = "yes" in rm.stdout.lower()
        return {"pct": pct, "muted": muted}
    except Exception:
        return None


def _fetch_brightness():
    """brightnessctl -m: '<device>,<class>,<current>,<percent>%,<max>' -
    percent is always the 4th field, regardless of the backlight's name/type."""
    try:
        r = subprocess.run(["brightnessctl", "-m"], capture_output=True, text=True, timeout=2)
        parts = r.stdout.strip().split(",")
        pct = int(parts[3].rstrip("%"))
        return {"pct": pct}
    except Exception:
        return None


def get_volume():
    data, ts = _av_cache["volume"]
    now = time.time()
    if now - ts < _AV_CACHE_TTL:
        return data
    data = _fetch_volume()
    _av_cache["volume"] = (data, now)
    return data


def get_brightness():
    data, ts = _av_cache["brightness"]
    now = time.time()
    if now - ts < _AV_CACHE_TTL:
        return data
    data = _fetch_brightness()
    _av_cache["brightness"] = (data, now)
    return data


VBARS_W = 11  # border+pad(2) + bar(3) + gap(1) + bar(3) + pad+border(2)


def draw_vbars(stdscr, volume, brightness, y0, x0, width, height):
    """Two vertical bars side by side (volume, brightness), in a frame. The
    right edge sits exactly on the screen's last column (see
    vbars_x/preview_w in main()) - there's no separate "outer frame"
    anymore, so no alignment tricks are needed. The bars do NOT reach all
    the way up - they're anchored to the bottom, with just a short label
    (VOL/BRI) right above them, leaving empty space at the top of the box.
    Plain white, no percentage number - the bar's height already conveys that."""
    draw_box(stdscr, y0, x0, height, width, False)
    content_rows = height - 2
    label_row = y0 + height - 2
    bar_bottom = label_row - 1
    bar_rows = max(content_rows - 1, 4)  # -1 = the VOL/BRI label row, the rest goes to the bar

    bar1_x = x0 + 2
    bar2_x = bar1_x + 4

    def draw_bar(bx, pct):
        pct = 0 if pct is None else pct
        pct = max(0, min(100, pct))
        filled = round(bar_rows * pct / 100)
        for i in range(bar_rows):
            row = bar_bottom - i
            if i < filled:
                safe_addstr(stdscr, row, bx, "███", curses.color_pair(1) | curses.A_BOLD)
            else:
                safe_addstr(stdscr, row, bx, "░░░", curses.color_pair(6))

    vol_pct = volume["pct"] if volume else None
    vol_muted = bool(volume and volume.get("muted"))
    draw_bar(bar1_x, 0 if vol_muted else vol_pct)

    bri_pct = brightness["pct"] if brightness else None
    draw_bar(bar2_x, bri_pct)

    safe_addstr(stdscr, label_row, bar1_x, "VOL", curses.color_pair(6))
    safe_addstr(stdscr, label_row, bar2_x, "BRI", curses.color_pair(6))


# ---------- right panel: compact calendar next to weather (passive view) ----------

def render_calendar_strip(stdscr, year, month, today_day, notes, y0, x0, width, height):
    """Passive full-month view, always visible next to Weather. The box has
    its own "Calendar [^K]" title in the top frame (same as "Weather"), the
    day-of-week header (Mo..Su) is a normal row inside the box above the
    grid. Any leftover space above the 6 weeks + header is spread out as
    padding, so the grid doesn't stick to the top."""
    draw_box(stdscr, y0, x0, height, width, False, "Calendar [^K]")
    weeks = calendar.monthcalendar(year, month)
    while len(weeks) < 6:
        weeks.append([0] * 7)

    col_w = max(min(width // 7, 6), 3)
    grid_w = col_w * 7
    grid_x0 = x0 + 1 + max((width - 2 - grid_w) // 2, 0)
    content_rows = height - 2
    pad_top = max((content_rows - 8) // 2, 0)  # 8 = 1 blank row + header + 6 weeks
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
            if d == today_day:
                style = curses.color_pair(3) | curses.A_REVERSE
            else:
                style = curses.color_pair(1) | curses.A_BOLD
            safe_addstr(stdscr, y, x, num_str[:col_w], style)
            if d in notes_days and len(num_str) < col_w:
                safe_addstr(stdscr, y, x + len(num_str), "●", curses.color_pair(4) | curses.A_BOLD)


WEEKDAY_NAMES = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
NOTES_PANEL_H = 9  # how many rows at the bottom are reserved for the notes list


def render_calendar(stdscr, year, month, day, notes, y0, x0, width, height,
                     interactive=True, panel_mode=False, notes_sel=0):
    """Pure rendering - used both for the hover preview and inside
    run_calendar. panel_mode=True means focus is on the notes list (not the
    day grid)."""
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

            if is_selected:
                num_color = curses.color_pair(7) | curses.A_BOLD
            elif is_today:
                num_color = curses.color_pair(8) | curses.A_BOLD
            else:
                num_color = curses.color_pair(1)
            safe_addstr(stdscr, cy + 1, cx + 2, f"{d:2d}", num_color)

            if n_notes and row_h > 2:
                dots = "•" * min(n_notes, 3) + (f" +{n_notes - 3}" if n_notes > 3 else "")
                safe_addstr(stdscr, cy + row_h - 2, cx + 2, dots[:col_w - 3], curses.color_pair(4))

    panel_y = grid_top + n_weeks * row_h + 1
    selected_key = note_key(year, month, day)
    day_notes = notes.get(selected_key, [])
    date_str = datetime.date(year, month, day).strftime("%d. %m. %Y")
    count_str = f"({len(day_notes)} notes)" if day_notes else "(no notes)"
    if panel_mode:
        panel_title_color = curses.color_pair(3) | curses.A_BOLD
    else:
        panel_title_color = curses.color_pair(2) | curses.A_BOLD
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


def run_calendar(stdscr, y0, x0, width, height, chrome_draw=None):
    """chrome_draw(stdscr), if given, is called EVERY frame right after
    erase() - needed because erase() now clears the whole screen (otherwise
    leftovers from the last regular frame, e.g. the VOL/BRI bars, would
    stay visible), which without this would also wipe the sidebar that
    used to only be drawn once."""
    today = datetime.date.today()
    year, month, day = today.year, today.month, today.day
    tab_held = False
    notes = load_notes()
    panel_mode = False
    notes_sel = 0

    while True:
        stdscr.erase()  # otherwise leftovers from the last regular frame (VOL/BRI bars etc.) stay visible
        if chrome_draw:
            chrome_draw(stdscr)
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
            # enter note-navigation mode for the selected day
            tab_held = False
            panel_mode = True
            notes_sel = 0

        elif panel_mode and key == curses.KEY_UP:
            notes_sel = max(0, notes_sel - 1)

        elif panel_mode and key == curses.KEY_DOWN:
            notes_sel = min(len(day_notes), notes_sel + 1)  # last index = "+ new note"

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


# ---------- right panel: timer (render + interactive loop) ----------

TIMER_LABELS = ["HH", "MM", "SS"]
TIMER_LIMITS = [99, 59, 59]


def start_timer(values):
    """Starts StickyTimer (termdown in kitty) with the currently set h/m/s.
    Returns True if it actually fired (total > 0), False otherwise."""
    total = values[0] * 3600 + values[1] * 60 + values[2]
    if total <= 0:
        return False
    subprocess.Popen(["swaymsg", "exec",
        f"kitty --class StickyTimer --override font_size=30 -e termdown {total}"])
    return True


# ---------- connectivity: pinned WiFi/BT boxes above the power menu ----------

_status_cache = {"wifi": (None, 0.0), "bt": (None, 0.0)}
_STATUS_CACHE_TTL = 2  # seconds - same idea as _wifi_preview_cache below,
                        # so the daemon isn't hit 3x/s by the 300ms refresh tick


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
    """Standard signal-quality estimate from dBm (same formula NetworkManager uses)."""
    try:
        pct = 2 * (int(dbm) + 100)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, pct))


BT_DEVICE_MAC = "1C:6E:4C:9C:D0:41"  # MAJOR IV headphones

# State of the last connection attempt - errors used to just get swallowed
# (bare except: pass), so "nothing happened" was literally true - no
# feedback at all, even when the connect failed. Now the state is shown
# directly in the box.
CONN_BOX_H = 3
CONN_STATUS_TTL = 6  # seconds an ok/error message stays visible before it disappears
_wifi_conn_state = {"status": "idle", "msg": "", "ts": 0.0}
_bt_conn_state = {"status": "idle", "msg": "", "ts": 0.0}


def _conn_status_line(state):
    """Returns (status, msg) to display, or (None, None) when there's
    nothing to report (idle, or an ok/error that already expired)."""
    if state["status"] == "connecting":
        return state["status"], state["msg"]
    if state["status"] in ("ok", "error") and time.time() - state["ts"] < CONN_STATUS_TTL:
        return state["status"], state["msg"]
    return None, None


def _last_line(text):
    lines = [l.strip() for l in _strip_ansi(text).strip().splitlines() if l.strip()]
    return lines[-1] if lines else "failed"


def connect_bluetooth_device(mac):
    """Connects a specific BT device in the background, the dashboard stays
    open - the status (battery/connected dot) picks it up automatically on
    the daemon's next refresh. Result (ok/error + the message from
    bluetoothctl) is reported into _bt_conn_state."""
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
    """iwctl colors its output even when not running in a tty (piped via
    subprocess), so lines contain escape sequences like '\\x1b[90m'.
    Without stripping this, separator-line detection ('----') breaks - the
    line then starts with an escape code instead of '-', falls through the
    filter, and gets parsed as a bogus network name."""
    return _ANSI_RE.sub("", text)


def _parse_iwctl_network_column(line):
    """iwctl tables separate columns with 2+ spaces. The currently connected
    network also has a '>' prefix, which has to go BEFORE splitting - other-
    wise '>' becomes its own "column" (since it's followed by 2+ spaces too,
    for alignment)."""
    line = line.strip()
    if line.startswith(">"):
        line = line[1:].strip()
    parts = re.split(r"\s{2,}", line)
    if not parts or not parts[0]:
        return None
    return parts[0].strip()


def get_available_wifi_networks():
    """SSIDs from the last scan, in the order iwctl returns them (usually by signal strength)."""
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
    """Strongest known network currently in range, WITHOUT triggering a new
    scan (just reads iwctl's last results, so it's fast) - used for the live
    preview in the box. Cached briefly (2s) so the subprocess doesn't get
    hit on every redraw."""
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
    """Connects to the given network right away if we already know it from
    the preview; otherwise falls back to Scan -> intersect available with
    known networks -> connect to the first match (iwctl's get-networks is
    roughly signal-strength ordered, so the first match should be the
    strongest known network available). Runs in the background. Result
    (ok/error + iwctl's message) is reported into _wifi_conn_state, so
    "nothing happened" after pressing Enter is now visible as a reason -
    failures used to be silently swallowed (bare except: pass)."""
    _wifi_conn_state.update(status="connecting",
                             msg=f"connecting {ssid}…" if ssid else "scanning…", ts=time.time())

    def worker():
        try:
            target = ssid
            if not target:
                subprocess.run(["iwctl", "station", "wlan0", "scan"], timeout=10,
                                capture_output=True)
                time.sleep(2)  # give the scan a moment to populate results
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


# ---------- right panel: app launcher (render + its own loop) ----------

def filter_apps(apps, query):
    if not query:
        return apps
    q = query.lower()
    return [a for a in apps if q in a[0].lower()]


def draw_matched(stdscr, y, x, text, query, max_w, base_style, match_style):
    """Draws text with the first match of query highlighted (case-insensitive)
    - immediately shows WHY this result showed up, instead of a bare listing."""
    text = text[:max_w]
    idx = text.lower().find(query.lower()) if query else -1
    if idx == -1:
        safe_addstr(stdscr, y, x, text, base_style)
        return
    safe_addstr(stdscr, y, x, text[:idx], base_style)
    safe_addstr(stdscr, y, x + idx, text[idx:idx + len(query)], match_style)
    safe_addstr(stdscr, y, x + idx + len(query), text[idx + len(query):], base_style)


LAUNCHER_STRIP_H = 4  # border(1) + query line(1) + app icons(1) + border(1)

# Monogram placeholder colors - cycled by app name so they're not all the
# same color. Once real .png icons exist (Icon= from .desktop + the kitty
# image protocol, same idea as the workspace preview), only
# _app_icon_placeholder() needs to change - callers in draw_launcher_strip
# stay the same (app name goes in, a "visual" comes out).
_MONOGRAM_COLORS = [3, 4, 2, 5]


def _app_icon_placeholder(name):
    """Placeholder icon: the app's first letter + a color derived from its
    name (same app = always the same color). Returns (letter, color_pair index)."""
    letter = (name.strip()[:1] or "?").upper()
    color_idx = _MONOGRAM_COLORS[sum(ord(c) for c in name) % len(_MONOGRAM_COLORS)]
    return letter, color_idx


CLOCK_W = 20  # width of the clock/date box carved out on the right of the launcher strip


def draw_launcher_strip(stdscr, query, results, sel, y0, x0, width, height, active=True):
    """Horizontal strip above the main preview + volume/brightness bars -
    apps left to right, each as [monogram] Name. Selected item is shown in
    reverse video. If the selected item doesn't fit in the window computed
    from the start of the list, the window gets recomputed to start right
    on it (a simple "snap" scroll with no need to keep an offset between
    frames).

    On the right there's a permanent little box with the current time/date,
    separated by a gap from the launcher (not just a vertical divider inside
    one box) - independent of whether search is active.

    Permanently reserved space (see main_y0/main_h in main()) - even while
    idle (active=False) this still gets drawn, just showing one hint instead
    of the query/results, so the preview+bars below don't jump around when
    search turns on/off."""
    clock_w = min(CLOCK_W, max(width // 4, 0))
    has_clock = clock_w >= 8 and height >= 3
    text_w = width - clock_w - 1 if has_clock else width  # -1 = gap between the two boxes

    draw_box(stdscr, y0, x0, height, text_w, active, "Launcher")

    if has_clock:
        clock_x = x0 + text_w + 1
        draw_box(stdscr, y0, clock_x, height, clock_w, False)
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%a %d.%m.")
        inner_rows = height - 2
        row1 = y0 + 1 + max((inner_rows - 2) // 2, 0)
        row2 = min(row1 + 1, y0 + height - 2)
        safe_addstr(stdscr, row1, clock_x + max((clock_w - len(time_str)) // 2, 0),
                    time_str, curses.color_pair(3) | curses.A_BOLD)
        safe_addstr(stdscr, row2, clock_x + max((clock_w - len(date_str)) // 2, 0),
                    date_str, curses.color_pair(6))

    query_row = y0 + 1
    items_row = y0 + 2
    avail_w = max(text_w - 4, 0)

    if not active:
        idle = "start typing to search apps…"
        safe_addstr(stdscr, items_row, x0 + text_w // 2 - len(idle) // 2, idle, curses.color_pair(6))
        return

    safe_addstr(stdscr, query_row, x0 + 2, f"> {query}"[:max(text_w - 4, 0)].ljust(max(text_w - 4, 0)),
                curses.color_pair(3) | curses.A_BOLD)

    if not results:
        safe_addstr(stdscr, items_row, x0 + 2, "(no match)", curses.color_pair(5))
    else:
        def item_width(name):
            return 4 + len(name[:14]) + 2  # "[X] " + label + trailing gap

        def build_window(start):
            cx, shown = 0, []
            for i in range(start, len(results)):
                iw = item_width(results[i][0])
                if cx + iw > avail_w and shown:
                    break
                shown.append(i)
                cx += iw
            return shown

        shown = build_window(0)
        if sel not in shown:
            shown = build_window(sel)

        cx = x0 + 2
        for i in shown:
            name, _cmd = results[i]
            letter, color_idx = _app_icon_placeholder(name)
            label = name[:14]
            is_sel = (i == sel)
            if is_sel:
                badge_style = curses.color_pair(7) | curses.A_REVERSE
                text_style = curses.color_pair(3) | curses.A_REVERSE
                match_style = curses.color_pair(3) | curses.A_REVERSE
            else:
                badge_style = curses.color_pair(color_idx) | curses.A_BOLD
                text_style = curses.color_pair(1)
                match_style = curses.color_pair(4) | curses.A_BOLD
            safe_addstr(stdscr, items_row, cx, f"[{letter}]", badge_style)
            draw_matched(stdscr, items_row, cx + 4, label, query, len(label), text_style, match_style)
            cx += item_width(name)
        if shown and shown[-1] < len(results) - 1:
            remaining = len(results) - 1 - shown[-1]
            safe_addstr(stdscr, items_row, cx, f"+{remaining}", curses.color_pair(6))


# ---------- sidebar: workspace boxes (1-10, always all of them) ----------

def _draw_window_line(stdscr, y, x, max_w, app, title, focused):
    """One line "app <condensed title>" - the app name in color (same color
    as its monogram in the launcher/preview), the condensed title dimmed
    next to it. See condense_title()."""
    if max_w <= 0:
        return
    _letter, color_idx = _app_icon_placeholder(app)
    app_style = curses.color_pair(3) | curses.A_BOLD if focused else curses.color_pair(color_idx)
    end = x + max_w
    chunk = app[:max_w]
    safe_addstr(stdscr, y, x, chunk, app_style)
    cx = x + len(chunk)

    detail = condense_title(app, title)
    if detail and cx + 1 < end:
        safe_addstr(stdscr, y, cx, f" {detail}"[:end - cx], curses.color_pair(6))


def _box_heights(win_counts, avail_h, count):
    """How many rows each workspace box gets. Every window wants its own
    line (an empty workspace gets one line for "empty"), plus 2 for the
    border - but it must NEVER get cut below 2 visible apps (no "+N more"
    hint is better than showing just one app, or none). When rows need to
    be taken away, they're taken FROM THE END (higher workspace numbers),
    not from the top - workspace 1 stays untouched for as long as
    possible. If even this minimum doesn't fit, returns None as a signal
    to fall back to the compact mode (see caller)."""
    min_lines = [min(max(n, 1), 2) for n in win_counts]  # at least 2 apps (or "empty"), never fewer
    if sum(min_lines) + 2 * count > avail_h:
        return None

    lines = [max(n, 1) for n in win_counts]
    for i in range(count - 1, -1, -1):
        while sum(lines) + 2 * count > avail_h and lines[i] > min_lines[i]:
            lines[i] -= 1
    return [n + 2 for n in lines]


def draw_workspace_boxes(stdscr, ws_apps, selected_num, y0, x0, width, avail_h, count=WS_COUNT):
    """count boxes (styled like the Timer/WiFi/BT boxes), one per workspace,
    ALWAYS all count of them - empty ones included, so the whole overview is
    visible at once with no scrolling. Every window gets its own line: app +
    its condensed title (see condense_title). Box height is driven by window
    count (see _box_heights); when there are more windows than fit, the last
    line shows "+N"."""
    safe_addstr(stdscr, y0, x0 + 2, "── Workspaces ──"[:width - 4], curses.color_pair(6))

    per_ws = [list(dict.fromkeys(ws_apps.get(i + 1, []))) for i in range(count)]  # dedupe, keep order
    heights = _box_heights([len(w) for w in per_ws], avail_h - 1, count)

    # compact fallback for small terminals - apps go straight into the box's title
    if heights is None:
        box_h = max((avail_h - 1) // count, 2)
        for i in range(count):
            windows = per_ws[i]
            apps = ", ".join(dict.fromkeys(app for app, _t in windows)) if windows else "empty"
            draw_box(stdscr, y0 + 1 + i * box_h, x0, box_h, width,
                     i + 1 == selected_num, f"{i + 1}: {apps}")
        return

    by = y0 + 1
    for i in range(count):
        num = i + 1
        box_h = heights[i]
        rows = box_h - 2
        focused = (num == selected_num)
        windows = per_ws[i]
        draw_box(stdscr, by, x0, box_h, width, focused, str(num))

        if not windows:
            safe_addstr(stdscr, by + 1, x0 + 2, "empty", curses.color_pair(6))
        else:
            if len(windows) <= rows:
                shown = windows
            elif rows >= 3:
                shown = windows[:rows - 1]  # last line is "+N more"
            else:
                # rows==2 (minimum) - two real apps win over the "+N more"
                # hint, which would just push one of them out
                shown = windows[:rows]
            for n, (app, title) in enumerate(shown):
                _draw_window_line(stdscr, by + 1 + n, x0 + 2, width - 4, app, title, focused)
            if len(shown) < len(windows) and len(shown) < rows:
                more = f"+{len(windows) - len(shown)} more"
                safe_addstr(stdscr, by + 1 + len(shown), x0 + 2, more[:width - 4], curses.color_pair(6))
        by += box_h


# ---------- sidebar ----------

def draw_sidebar(stdscr, items, selected, y0, x0, width, height, power_start,
                  timer_values, timer_field, ws_apps, focused=True):
    """The full sidebar - 10 workspace boxes on top (see draw_workspace_boxes),
    pinned Timer/WiFi/BT/PowerMenu at the bottom."""
    draw_box(stdscr, y0, x0, height, width, focused)

    power_block_h = len(POWER_OPTIONS) + 2
    conn_block_h = 3 * CONN_BOX_H + 1  # Timer + WiFi + BT boxes + 1 line of separation
    content_h = height - 2 - power_block_h - conn_block_h

    selected_ws_num = items[selected][0] if items[selected][1] == "workspace" else None
    ws_y = y0 + 1
    ws_avail = content_h - 1

    # --- workspace boxes 1-10, ALWAYS all visible, no scrolling ---
    draw_workspace_boxes(stdscr, ws_apps, selected_ws_num, ws_y, x0, width, ws_avail)

    # --- pinned Timer/WiFi/BT boxes, right above PowerMenu ---
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
    wifi_title = "WiFi  ^W impala" if wifi_focused else "WiFi"
    draw_box(stdscr, wifi_box_y, x0, CONN_BOX_H, width, wifi_focused, wifi_title)
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
    bt_title = "Bluetooth  ^B bluetuith" if bt_focused else "Bluetooth"
    draw_box(stdscr, bt_box_y, x0, CONN_BOX_H, width, bt_focused, bt_title)
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

    # --- pinned PowerMenu, unchanged ---
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
    stdscr.timeout(300)  # non-blocking getch -> the dashboard redraws itself
                          # even without a keypress (WiFi signal / BT battery
                          # and connection status catch up almost instantly after Enter)

    workspaces, ws_apps, ws_layout = get_workspaces_cached()

    sidebar_items = [(num, "workspace", "") for num in range(1, WS_COUNT + 1)]
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
    CALENDAR_KEY = ctrl("K")  # not Ctrl+C - that's SIGINT, the terminal would eat it before curses sees it
    WIFI_TUI_KEY = ctrl("W")
    BT_TUI_KEY = ctrl("B")

    all_apps = scan_desktop_apps()
    timer_values = [0, 0, 0]
    timer_field = 0
    WEATHER_STRIP_H = 10

    # The launcher is normally not visible at all - no entry in
    # sidebar_items, no Tab-cycling. It appears as soon as you type anything
    # printable (see the "start typing" branch below), from anywhere in the
    # dashboard.
    launcher_active = False
    launcher_query = ""
    launcher_sel = 0
    launcher_return_sel = 0  # sidebar selection to restore focus to once the launcher closes

    while True:
        stdscr.erase()  # not clear() - that force-touches the whole window and causes flicker
        workspaces, ws_apps, ws_layout = get_workspaces_cached()  # TTL cache - see get_workspaces_cached()
        h, w = stdscr.getmaxyx()
        side_w = max(w // 5, 20)
        cx0, cy0 = side_w + 1, 0
        cwidth = (w - side_w) - 2
        cheight = h - WEATHER_STRIP_H
        # main_pane_w is 1 wider than cwidth - that makes the right edge of
        # the vbars box line up flush with the outer frame, instead of
        # sitting one column inset and creating a "detached" double line.
        # Calendar/Weather below (cwidth unchanged) keep the normal inset.
        main_pane_w = cwidth + 1
        preview_w = main_pane_w - VBARS_W - 1  # -1 = gap between the preview and the bars
        vbars_x = cx0 + preview_w + 1
        strip_y = cy0 + cheight
        # the bottom strip reaches the same right edge as the preview+bars
        # above it (main_pane_w, not cwidth), so weather ends exactly in the corner
        cal_w = (main_pane_w - 1) * 2 // 5  # 2:3 ratio, calendar:weather
        weather_x = cx0 + cal_w + 1
        weather_w = main_pane_w - cal_w - 1

        # The launcher is a horizontal strip ABOVE the preview+bars -
        # permanently reserved (not just while typing), so the preview/bars
        # don't shift when search starts/stops. Calendar/Weather below stay
        # untouched (strip_y is computed from cheight above, not from main_h).
        main_y0 = cy0 + LAUNCHER_STRIP_H
        main_h = cheight - LAUNCHER_STRIP_H

        launcher_results = filter_apps(all_apps, launcher_query) if launcher_active else []
        if launcher_sel >= len(launcher_results):
            launcher_sel = max(len(launcher_results) - 1, 0)

        # h (not h-1) - no reserved bottom row. draw_box is wrapped in a
        # try/except curses.error, so even if writing to the screen's very
        # last corner hits an old ncurses quirk (addch in a window's
        # bottom-right corner can raise), nothing breaks - at worst that one
        # corner just doesn't get drawn.
        draw_sidebar(stdscr, sidebar_items, sel_side, 0, 0, side_w, h, power_start,
                     timer_values, timer_field, ws_apps, focused=True)
        today = datetime.date.today()
        render_calendar_strip(stdscr, today.year, today.month, today.day, load_notes_cached(),
                               strip_y, cx0, cal_w, WEATHER_STRIP_H)
        draw_weather_strip(stdscr, strip_y, weather_x, weather_w, WEATHER_STRIP_H)

        draw_launcher_strip(stdscr, launcher_query, launcher_results, launcher_sel,
                             cy0, cx0, main_pane_w, LAUNCHER_STRIP_H, active=launcher_active)

        item_id, kind, _extra = sidebar_items[sel_side]

        # One big preview of WHATEVER is Tab-selected in the sidebar right
        # now - for a workspace, purely from live sway tree data
        # (draw_workspace_tile, no screenshot/photographer), for Power a
        # classic text preview.
        if kind == "workspace":
            draw_workspace_tile(stdscr, item_id, ws_layout.get(item_id), main_y0, cx0, preview_w, main_h,
                                 corners_only=True)
        elif kind == "power":
            draw_power_preview(stdscr, item_id, main_y0, cx0, preview_w, main_h)
        # wifi/bt/timer: status and controls happen right in their pinned sidebar box

        # volume/brightness bars - always to the right of the preview, same height (not over weather)
        draw_vbars(stdscr, get_volume(), get_brightness(), main_y0, vbars_x, VBARS_W, main_h)

        stdscr.refresh()
        key = stdscr.getch()

        # global shortcuts - work from anywhere in the main loop.
        # PowerMenu + Calendar go through Ctrl (control codes 1-26 aren't
        # printable characters, so they never collide with typing into the
        # AppLauncher, or with Shift). Calendar is on Ctrl+K, not Ctrl+C -
        # Ctrl+C is SIGINT and the terminal would eat it before it ever
        # reaches getch().
        if key in power_keys:
            close_self()
            _kitty_clear_placements()
            subprocess.Popen(power_keys[key], start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if key == CALENDAR_KEY:
            _kitty_clear_placements()  # run_calendar has its own loop - the main tick that otherwise clears stale thumbnails never runs while it's up
            run_calendar(stdscr, cy0, cx0, cwidth, cheight, chrome_draw=lambda s: draw_sidebar(
                s, sidebar_items, sel_side, 0, 0, side_w, h, power_start,
                timer_values, timer_field, ws_apps, focused=False))
            continue
        if key == WIFI_TUI_KEY:
            close_self()
            _kitty_clear_placements()
            open_wifi_manager()
            return
        if key == BT_TUI_KEY:
            close_self()
            _kitty_clear_placements()
            open_bt_manager()
            return

        # "start typing" - any printable character anywhere in the dashboard
        # opens the launcher (dmenu/rofi style). Range 32-126 never collides
        # with Ctrl codes (1-26) or Tab/Enter/Esc (9/10/13/27).
        if not launcher_active and 32 <= key <= 126:
            launcher_active = True
            launcher_query = chr(key)
            launcher_sel = 0
            launcher_return_sel = sel_side  # where focus returns to on Enter/Esc
            continue

        if launcher_active:
            if key == 27:
                launcher_active = False
                launcher_query = ""
                sel_side = launcher_return_sel
            elif key == ord('\t'):
                launcher_active = False  # Tab = "leave search", not "jump elsewhere" in the same keypress
                sel_side = launcher_return_sel
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if launcher_query:
                    launcher_query = launcher_query[:-1]
                    launcher_sel = 0
                else:
                    launcher_active = False
                    sel_side = launcher_return_sel
            elif key == curses.KEY_LEFT:
                launcher_sel = max(launcher_sel - 1, 0)
            elif key == curses.KEY_RIGHT:
                launcher_sel = min(launcher_sel + 1, max(len(launcher_results) - 1, 0))
            elif key in (10, 13):
                if launcher_results:
                    cmd = launcher_results[launcher_sel][1]
                    # item_id/kind come from the sidebar selection (see
                    # earlier in this same loop iteration) - if a workspace
                    # is Tab-focused, the app quietly ends up there in the
                    # background. The dashboard does NOT close (see
                    # launch_app_on_workspace), but the launcher doesn't
                    # keep focus after launching - it returns to wherever it
                    # was before being opened. The next app launches simply
                    # by typing again.
                    target_num = item_id if kind == "workspace" else None
                    launch_app_on_workspace(cmd, target_num)
                    launcher_active = False
                    launcher_query = ""
                    launcher_sel = 0
                    sel_side = launcher_return_sel
            elif 32 <= key <= 126:
                launcher_query += chr(key)
                launcher_sel = 0
            continue

        item_id, kind, _extra = sidebar_items[sel_side]

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
                # works even on a workspace that doesn't physically exist
                # yet - `swaymsg workspace number N` creates it on its own
                close_self()
                _kitty_clear_placements()
                switch_workspace(item_id)
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
                    if name_ == item_id:
                        close_self()
                        _kitty_clear_placements()
                        subprocess.Popen(cmd_, start_new_session=True,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return


if __name__ == "__main__":
    curses.wrapper(main)
