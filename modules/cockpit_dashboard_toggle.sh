#!/usr/bin/env bash
# cockpit_dashboard_toggle.sh — Win+grave toggle pro cockpit_dashboard.py
# Pokud CockpitDashboard okno běží, zavře ho. Jinak ho spustí.

if swaymsg -t get_tree | grep -q '"app_id": *"CockpitDashboard"'; then
    swaymsg '[app_id="CockpitDashboard"] kill'
else
    rm -f /tmp/cockpit-dashboard.sock
    kitty --class CockpitDashboard \
        -e python3 ~/scripts_sway/cockpit_dashboard.py &
fi
