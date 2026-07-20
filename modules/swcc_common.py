#!/usr/bin/env python3
"""
swcc_common.py — sdílená helper funkce pro widgety, co chtějí číst
data z swccd.py místo přímého fetche.

Použití ve widgetu:
    from swcc_common import query_daemon

    def get_weather():
        cached = query_daemon("weather")
        if cached is not None:
            return cached
        # fallback: přímý fetch, pokud daemon neběží
        ...
"""
import socket
import os
import json

SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "swcc.sock")


def query_daemon(key, timeout=0.5):
    """Zeptá se swccd.py na klíč ('weather' | 'wifi' | 'bt' | 'all').
    Vrací parsovaný JSON, nebo None pokud daemon neběží / neodpoví včas."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(SOCK_PATH)
        s.sendall(f"GET {key}".encode())
        chunks = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
        s.close()
        data = b"".join(chunks).decode().strip()
        if not data or data == "null":
            return None
        return json.loads(data)
    except Exception:
        return None
