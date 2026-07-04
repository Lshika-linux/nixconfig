#!/usr/bin/env python3
"""
cockpit_daemon.py — background data cache for the cockpit TUI widgets.

Holds wifi / bluetooth / weather state in memory, refreshed on separate
intervals, and serves it over a unix socket so widgets open instantly
instead of blocking on network/iwctl/bluetoothctl calls.

Protocol (plain text over AF_UNIX):
    request:  "GET weather" | "GET wifi" | "GET bt" | "GET all" | "PING"
    response: JSON line (or "PONG")
"""
import socket
import subprocess
import threading
import json
import time
import os

SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "cockpit.sock")

WEATHER_INTERVAL = 900   # 15 min
CONN_INTERVAL = 10       # 10s

cache = {
    "weather": None,
    "wifi": None,
    "bt": None,
}
lock = threading.Lock()


# ---------- fetchers (logika 1:1 podle weather.py / connectivity.py) ----------

def fetch_weather():
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
            weather["forecast"].append({
                "date": day["date"],
                "max": day["maxtempC"],
                "min": day["mintempC"],
                "desc": day["hourly"][4]["weatherDesc"][0]["value"]
            })
        return weather
    except Exception:
        return None


def fetch_wifi():
    try:
        r = subprocess.run(
            ["iwctl", "station", "wlan0", "show"],
            capture_output=True, text=True, timeout=5
        )
        ssid = None
        rssi = None
        for line in r.stdout.split("\n"):
            if "Connected network" in line:
                ssid = line.split()[-1]
            if "AverageRSSI" in line:
                rssi = line.split()[-2]
        if ssid:
            return {"ssid": ssid, "rssi": rssi}
    except Exception:
        pass
    return None


def fetch_bt():
    try:
        r = subprocess.run(
            ["bluetoothctl", "devices", "Paired"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            mac = parts[1]
            name = parts[2]
            info = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True, text=True, timeout=5
            )
            connected = "Connected: yes" in info.stdout
            battery = None
            for l in info.stdout.split("\n"):
                if "Battery Percentage" in l:
                    try:
                        battery = l.split("(")[1].split(")")[0] + "%"
                    except Exception:
                        pass
            if connected:
                return {"name": name, "battery": battery}
    except Exception:
        pass
    return None


# ---------- background refresh loops ----------

def weather_loop():
    while True:
        data = fetch_weather()
        with lock:
            cache["weather"] = data
        time.sleep(WEATHER_INTERVAL)


def conn_loop():
    while True:
        wifi = fetch_wifi()
        bt = fetch_bt()
        with lock:
            cache["wifi"] = wifi
            cache["bt"] = bt
        time.sleep(CONN_INTERVAL)


# ---------- socket server ----------

def handle_client(conn):
    try:
        data = conn.recv(1024).decode().strip()
        if not data:
            return
        parts = data.split()
        cmd = parts[0]
        key = parts[1] if len(parts) > 1 else None

        if cmd == "PING":
            conn.sendall(b"PONG\n")
        elif cmd == "GET" and key == "all":
            with lock:
                result = dict(cache)
            conn.sendall((json.dumps(result) + "\n").encode())
        elif cmd == "GET" and key in cache:
            with lock:
                result = cache[key]
            conn.sendall((json.dumps(result) + "\n").encode())
        else:
            conn.sendall(b"null\n")
    except Exception:
        pass
    finally:
        conn.close()


def main():
    if os.path.exists(SOCK_PATH):
        os.remove(SOCK_PATH)

    # prvotní fetch hned při startu, ať cache není prázdná
    with lock:
        cache["weather"] = fetch_weather()
        cache["wifi"] = fetch_wifi()
        cache["bt"] = fetch_bt()

    threading.Thread(target=weather_loop, daemon=True).start()
    threading.Thread(target=conn_loop, daemon=True).start()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o600)
    server.listen(8)

    try:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
    finally:
        server.close()
        if os.path.exists(SOCK_PATH):
            os.remove(SOCK_PATH)


if __name__ == "__main__":
    main()
