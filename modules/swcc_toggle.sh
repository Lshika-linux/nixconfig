#!/usr/bin/env bash
# swcc_dashboard_toggle.sh — Win+grave toggle pro swcc.py
# Pokud swcc okno běží, zavře ho. Jinak ho spustí.

if swaymsg -t get_tree | grep -q '"app_id": *"SwayControlCenter"'; then
    swaymsg '[app_id="SwayControlCenter"] kill'
else
    rm -f /tmp/swcc.sock
    kitty --class SwayControlCenter \
        -e python3 ~/scripts_sway/swcc.py &
fi
