#!/usr/bin/env python3
import curses
import subprocess
import json

from cockpit_common import query_daemon

def get_weather():
    cached = query_daemon("weather")
    if cached is not None:
        return cached

    # fallback: daemon neběží, fetchni přímo
    try:
        r = subprocess.run(
            ["curl", "-s", "wttr.in/?format=j1"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        current = data["current_condition"][0]
        area = data["nearest_area"][0]
        city = area["areaName"][0]["value"]
        country = area["country"][0]["value"]

        weather = {
            "city": f"{city}, {country}",
            "temp": current["temp_C"],
            "feels": current["FeelsLikeC"],
            "desc": current["weatherDesc"][0]["value"],
            "humidity": current["humidity"],
            "wind": current["windspeedKmph"],
            "forecast": []
        }

        for day in data["weather"][:3]:
            date = day["date"]
            max_t = day["maxtempC"]
            min_t = day["mintempC"]
            desc = day["hourly"][4]["weatherDesc"][0]["value"]
            weather["forecast"].append({
                "date": date,
                "max": max_t,
                "min": min_t,
                "desc": desc
            })

        return weather
    except:
        return None


# weather condition to simple ascii icon
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

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_RED, -1)
    curses.init_pair(6, curses.COLOR_BLACK+8, -1)
    stdscr.keypad(True)

    # loading screen
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    loading = "fetching weather..."
    try:
        stdscr.addstr(h//2, w//2 - len(loading)//2, loading, curses.color_pair(3))
    except curses.error:
        pass
    stdscr.refresh()

    weather = get_weather()

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        if not weather:
            try:
                stdscr.addstr(h//2, w//2 - 7, "no data", curses.color_pair(5))
                stdscr.addstr(h//2 + 1, w//2 - 10, "r to retry   Esc close", curses.color_pair(2))
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key == 27:
                return
            elif key == ord('r'):
                weather = get_weather()
            continue

        row = 0

        # City
        try:
            city_str = weather["city"]
            stdscr.addstr(row, w//2 - len(city_str)//2, city_str, curses.color_pair(2) | curses.A_BOLD)
            row += 1
        except curses.error:
            pass

        # Current temp + icon
        icon = weather_icon(weather["desc"])
        temp_str = f"{icon}  {weather['temp']}°C"
        try:
            stdscr.addstr(row, w//2 - len(temp_str)//2, temp_str, curses.color_pair(3) | curses.A_BOLD)
            row += 1
        except curses.error:
            pass

        # Desc + feels like
        desc_str = f"{weather['desc']}"
        feels_str = f"feels {weather['feels']}°C"
        try:
            stdscr.addstr(row, w//2 - len(desc_str)//2, desc_str, curses.color_pair(1))
            row += 1
            stdscr.addstr(row, w//2 - len(feels_str)//2, feels_str, curses.color_pair(6))
            row += 1
        except curses.error:
            pass

        # Wind + humidity
        info_str = f"💨 {weather['wind']} km/h   💧 {weather['humidity']}%"
        try:
            stdscr.addstr(row, w//2 - len(info_str)//2, info_str, curses.color_pair(6))
            row += 2
        except curses.error:
            pass

        # Divider
        try:
            stdscr.addstr(row, 1, "─" * (w - 2), curses.color_pair(6))
            row += 1
        except curses.error:
            pass

        # Forecast
        if weather["forecast"]:
            col_w = (w - 2) // 3
            for i, day in enumerate(weather["forecast"]):
                x = 1 + i * col_w
                icon_f = weather_icon(day["desc"])
                date_parts = day["date"].split("-")
                date_short = f"{date_parts[2]}.{date_parts[1]}"
                temp_range = f"{day['min']}–{day['max']}°C"
                try:
                    stdscr.addstr(row, x, date_short.center(col_w - 1), curses.color_pair(2))
                    stdscr.addstr(row + 1, x, (icon_f + " " + day["desc"][:col_w-4]).center(col_w - 1), curses.color_pair(1))
                    stdscr.addstr(row + 2, x, temp_range.center(col_w - 1), curses.color_pair(3))
                except curses.error:
                    pass

        # Hints
        hints = "r refresh   Esc close"
        try:
            stdscr.addstr(h - 1, w//2 - len(hints)//2, hints, curses.color_pair(2))
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()
        if key == 27:
            return
        elif key == ord('r'):
            stdscr.clear()
            try:
                stdscr.addstr(h//2, w//2 - 7, "refreshing...", curses.color_pair(3))
            except curses.error:
                pass
            stdscr.refresh()
            weather = get_weather()

curses.wrapper(main)
