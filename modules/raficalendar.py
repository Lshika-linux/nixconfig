#!/usr/bin/env python3
import curses
import calendar
import datetime
import json
import os

NOTES_FILE = os.path.expanduser("~/.local/share/calendar_notes.json")

def load_notes():
    try:
        with open(NOTES_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_notes(notes):
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f)

def note_key(year, month, day):
    return f"{year}-{month:02d}-{day:02d}"

def get_input(stdscr, prompt, y, x, existing=""):
    curses.curs_set(1)
    stdscr.addstr(y, x, prompt + " " * 40)
    stdscr.addstr(y, x + len(prompt), existing)
    stdscr.refresh()
    text = list(existing)
    while True:
        key = stdscr.getch()
        if key in (10, 13):
            break
        elif key == 27:
            text = list(existing)
            break
        elif key in (curses.KEY_BACKSPACE, 127):
            if text:
                text.pop()
        elif 32 <= key <= 126:
            text.append(chr(key))
        stdscr.addstr(y, x + len(prompt), "".join(text).ljust(40))
        stdscr.refresh()
    curses.curs_set(0)
    return "".join(text).strip()

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_GREEN, -1)
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)
    stdscr.keypad(True)

    today = datetime.date.today()
    year = today.year
    month = today.month
    day = today.day
    tab_held = False
    notes = load_notes()

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        cal = calendar.monthcalendar(year, month)
        month_name = datetime.date(year, month, 1).strftime("%B %Y")

        # Header
        try:
            stdscr.addstr(0, w//2 - len(month_name)//2, month_name, curses.color_pair(2) | curses.A_BOLD)
        except curses.error:
            pass

        # Day headers
        days_header = " Mo  Tu  We  Th  Fr  Sa  Su"
        try:
            stdscr.addstr(1, w//2 - len(days_header)//2, days_header, curses.color_pair(4))
        except curses.error:
            pass

        x_start = w//2 - len(days_header)//2

        # Calendar grid
        for week_i, week in enumerate(cal):
            for day_i, d in enumerate(week):
                if d == 0:
                    continue
                x = x_start + day_i * 4
                y = week_i + 2
                key = note_key(year, month, d)
                has_note = key in notes and notes[key]
                dot = "•" if has_note else " "

                is_today = (d == today.day and month == today.month and year == today.year)
                is_selected = (d == day)

                label = f"{d:2d}{dot}"

                try:
                    if is_selected:
                        stdscr.addstr(y, x, label, curses.color_pair(6) | curses.A_BOLD)
                    elif is_today:
                        stdscr.addstr(y, x, label, curses.color_pair(3) | curses.A_BOLD)
                    elif has_note:
                        stdscr.addstr(y, x, label, curses.color_pair(5))
                    else:
                        stdscr.addstr(y, x, label, curses.color_pair(1))
                except curses.error:
                    pass

        # Note preview
        note_y = len(cal) + 3
        selected_key = note_key(year, month, day)
        note_text = notes.get(selected_key, "")
        date_str = datetime.date(year, month, day).strftime("%d. %m. %Y")

        try:
            stdscr.addstr(note_y, 1, f"{date_str}", curses.color_pair(2))
            if note_text:
                stdscr.addstr(note_y + 1, 1, note_text[:w-2], curses.color_pair(1))
            else:
                stdscr.addstr(note_y + 1, 1, "no note", curses.color_pair(4))
        except curses.error:
            pass

        # Hints
        hints = "↑↓←→ navigate   Tab+←→ month   Enter note   Esc close"
        try:
            stdscr.addstr(h - 1, w//2 - len(hints)//2, hints, curses.color_pair(2))
        except curses.error:
            pass

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
                    month = 12
                    year -= 1
                # clamp day
                max_day = calendar.monthrange(year, month)[1]
                day = min(day, max_day)
                tab_held = False
            else:
                # move day left
                new_day = day - 1
                if new_day < 1:
                    month -= 1
                    if month < 1:
                        month = 12
                        year -= 1
                    day = calendar.monthrange(year, month)[1]
                else:
                    day = new_day

        elif key == curses.KEY_RIGHT:
            if tab_held:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                max_day = calendar.monthrange(year, month)[1]
                day = min(day, max_day)
                tab_held = False
            else:
                max_day = calendar.monthrange(year, month)[1]
                new_day = day + 1
                if new_day > max_day:
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    day = 1
                else:
                    day = new_day

        elif key == curses.KEY_UP:
            tab_held = False
            new_day = day - 7
            if new_day < 1:
                month -= 1
                if month < 1:
                    month = 12
                    year -= 1
                max_day = calendar.monthrange(year, month)[1]
                day = max_day + new_day
            else:
                day = new_day

        elif key == curses.KEY_DOWN:
            tab_held = False
            max_day = calendar.monthrange(year, month)[1]
            new_day = day + 7
            if new_day > max_day:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                day = new_day - max_day
            else:
                day = new_day

        elif key in (10, 13):
            tab_held = False
            note_y_input = len(cal) + 4
            existing = notes.get(selected_key, "")
            result = get_input(stdscr, "> ", note_y_input, 1, existing)
            if result:
                notes[selected_key] = result
            elif selected_key in notes:
                del notes[selected_key]
            save_notes(notes)

        else:
            tab_held = False

curses.wrapper(main)
