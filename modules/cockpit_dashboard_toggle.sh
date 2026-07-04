#!/usr/bin/env bash
# cockpit_dashboard_toggle.sh — Win+grave toggle pro cockpit_dashboard.py
# Pokud CockpitDashboard okno běží, zavře ho. Jinak ho spustí.

if swaymsg -t get_tree | grep -q '"app_id": *"CockpitDashboard"'; then
    swaymsg '[app_id="CockpitDashboard"] kill'
else
    # stará socketka po neuklizeném běhu by bránila kitty v --listen-on bindu
    rm -f /tmp/cockpit-dashboard.sock
    kitty --class CockpitDashboard \
        -o allow_remote_control=yes \
        --listen-on unix:/tmp/cockpit-dashboard.sock \
        -e python3 ~/scripts_sway/cockpit_dashboard.py &
fi
