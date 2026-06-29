# nixconfig

My NixOS + Sway WM configuration. I'm learning as I go — I don't fully understand everything in here, and a lot of it is heavily AI-assisted. If something looks weird, it probably is.

## What's in here

- **Sway WM** config with a custom TUI-based desktop cockpit
- **i3status** bar with keyboard layout indicator
- **Home Manager** for user-level config

## The TUI cockpit // WORK IN PROGRESS

Instead of rofi or waybar widgets, I am building floating kitty terminal windows with curses Python scripts, one for each corner of the screen:

| Corner | Keybind | What it does |
|--------|---------|--------------|
| Top right | `Win+T` | Timer picker → launches termdown countdown |
| Top left | `Win+Tab` | Window switcher |
| Bottom left | `Win+D` | App launcher with search |
| Bottom right | `Win+Shift+E` | Power menu |

## Disclaimer

I'm learning NixOS and Linux ricing. This config works on my machine (ThinkPad T480) but I make no promises. Commit messages are honest.

**If you somehow come across this, and wanna help me or are interested in anything here, DM me!!**
