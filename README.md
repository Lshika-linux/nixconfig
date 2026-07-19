# nixconfig

My NixOS + Sway WM configuration. I'm learning as I go — I don't fully understand everything in here, and a lot of it is heavily AI-assisted. If something looks weird, it probably is.

Running on a ThinkPad T480.

## What's in here

- **Sway WM** config, plus **swcc** — my own fullscreen TUI control center
- **i3status** bar with keyboard layout indicator
- **Home Manager** for user-level config
- Config split into `modules/`, with `wallpapers/` and `sounds/` alongside

## swcc — Sway Control Center // WORK IN PROGRESS

This used to be four separate floating kitty windows, one in each corner — timer, window switcher, launcher, power menu. That's gone. It's now **one fullscreen curses dashboard** on `Win+grave` that does all of it in a single view.

### Layout

| Region | What's there |
| --- | --- |
| Sidebar | 10 fixed workspace boxes — running apps and condensed window titles |
| Main preview | Live render of the selected workspace's tiling layout, reconstructed from `swaymsg -t get_tree` |
| Launcher strip | Horizontal row of app monograms with snap-scrolling; clock and date pinned on the right |
| Widgets | Vertical volume and brightness bars |

Window titles are condensed per app type — browsers show the site domain (`claude.ai`, `youtube.com`), terminals show the path, Obsidian shows just the note name.

The preview is drawn from the sway tree rather than screenshots, so there's no photographer daemon grabbing frames in the background anymore. The dashboard's own window slot gets redistributed to its siblings so the preview shows what the workspace actually looks like without it.

### Keys

| Key | What it does |
| --- | --- |
| `Win+Tab` | Toggle swcc |
| `Tab` | Switch selected workspace |
| `Ctrl+W` | Wi-Fi — floating kitty running `impala` |
| `Ctrl+B` | Bluetooth — floating kitty running `bluetuith` |

Launching an app doesn't close the dashboard. swcc spawns it, then silently moves the new window onto whichever workspace is selected by polling the sway tree in the background.

### Files

| File | Role |
| --- | --- |
| `swcc.py` | The dashboard (`app_id: SwayControlCenter`) |
| `swcc_common.py` | Unix socket client helper — `$XDG_RUNTIME_DIR/swcc.sock` |
| `swcc_daemon.py` | Background cache daemon: weather, Wi-Fi, Bluetooth |
| `swcc_toggle.sh` | Toggle wrapper for the keybind |

Wired into the flake through `scripts.nix`.

## Disclaimer

I'm learning NixOS and Linux ricing. This config works on my machine but I make no promises. Commit messages are honest.

**If you somehow come across this, and wanna help me or are interested in anything here, DM me!!**
