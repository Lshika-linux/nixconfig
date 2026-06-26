#home.nix - here we declare packages for the user layer, generally no root requirement#
# also the home for configs n such.. #


{ config, pkgs, ... }:

{
  home.username = "rafi";
  home.homeDirectory = "/home/rafi";
  home.stateVersion = "24.11";
  xdg.enable = true;
  	
  # 1. Uživatelské balíčky spravované přes Home Manager
  home.packages = with pkgs; [
    swaybg
    obsidian
    wlogout
    fastfetch
    alacritty
    rofi           # rofi-wayland byl sloučen zpět do rofi
    i3status
    blanket        # Pro zkratku $mod+B
    libinput-gestures
    inter          # Inter font použitý v sway config (font pango:Inter)
    ubuntu-classic # Ubuntu font pro bar (dříve ubuntu_font_family)
    mpv           # Pro meow.mp3 při startu
    gnome-themes-extra  # Pro Adwaita-dark GTK téma
  ];

  # 2. Nastavení emulátoru terminálu Kitty (Tvoje barvy zůstávají netknuté)
  programs.kitty = {
      enable = true;
      settings = {
        background_opacity = "0.85";
        font_size = "12.0";
        confirm_os_window_close = 0;
        foreground = "#cdd6f4";
        background = "#1a1e2e";#282a36
        cursor     = "#c8848b";
  
        color0  = "#2e3a59";
        color1  = "#e06060";
        color2  = "#5b8dd9";
        color3  = "#c8848b";
        color4  = "#5b8dd9";
        color5  = "#c8848b";
        color6  = "#88c0d0";
        color7  = "#cdd6f4";
      };
  };

  programs.i3status = {
    enable = true;
    general = {
      interval = 1;
      colors = true;
      color_good = "#ffffff";
      color_degraded = "#ffff00";
      color_bad = "#ff0000";   
    };
    
    modules = {
      "wireless _first_" = {
        position = 1;
        settings = {
          format_up = "W: (%bitrate %quality at %essid) %ip";
          format_down = "W: down";
        };
      };
      "battery 0" = {
        position = 2;
        settings = {
          format = "PWR/INT: %status %percentage [%remaining]";
          path = "/sys/class/power_supply/BAT0/uevent";
        };
      };
      "battery 1" = {
        position = 3;
        settings = {
          format = "PWR/EXT: %status %percentage [%remaining]";
          path = "/sys/class/power_supply/BAT1/uevent";
        };
      };
      "volume master" = {
        position = 4;
        settings = {
          format = "VOL:    %volume";
          format_muted = "VOL:  MUTED";
          device = "default"; # Správné mapování pro PipeWire emulaci zvuku
        };
      };
      "load" = {
        position = 5;
        settings = { format = "LOAD:%1min"; };
      };
      "cpu_usage" = {
        position = 6;
        settings = { format = "CPU: %usage"; };
      };
      "cpu_temperature 0" = {
        position = 7;
        settings = {
          format = "CPUTEMP: %degrees °C";
          max_threshold = 80;
        };
      };
      "memory" = {
        position = 8;
        settings = {
          format = "MEM[U/A]: %used/%available";
          threshold_degraded = "1G";
          format_degraded = "MEM < %available";
        };
      };
      "tztime local" = {
        position = 9;
        settings = { format = "%d-%m-%y %H:%M:%S"; };
      };
    };
  };

  # Kompletní konfigurace okenního manažeru Sway
  wayland.windowManager.sway = {
    enable = true;
    config = {
      modifier = "Mod4";
      terminal = "alacritty"; # Přesně podle tvého i3 nastavení

      fonts = {
        names = [ "Inter" ];
        size = 12.0;
      };

     # ---- wallpaper ----
      output = {
        "*" = {
          bg = "${./wallpapers/wallpaper.png} fill";
        };
      };
     # ---------------------------

      # Vstupy a chování hardwaru (Touchpad a Trackpoint)
      input = {
        "type:keyboard" = {
          xkb_layout = "us,cz";
          xkb_options = "grp:win_space_toggle";
        };
        "2:7:SynPS/2_Synaptics_TouchPad" = {
          tap = "enabled";
          natural_scroll = "enabled";
        };
        "TPPS/2 IBM TrackPoint" = {
          events = "disabled"; # Úplné hardwarové odstavení zlobivého trackpointu
        };
      };

      # Autostart tvých skriptů a démonů na pozadí
      startup = [
        # GTK téma je nastaveno přes gtk.theme níže — exec zde není potřeba
        { command = "libinput-gestures-setup start"; always = false; }
        { command = "gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'"; always = false; }
        { command = "mpv --no-video ~/scripts_sway/meow.mp3"; } # Počáteční mňouknutí
        { command = "~/scripts_sway/chargersound.sh"; }
      ];

      # Nastavení mezer (gaps) a ohraničení oken
      gaps = {
        inner = 2;
        outer = 0;
        smartBorders = "on";
        smartGaps = true;
      };

      window.border = 4;
      floating.border = 4;

      # Pravidla chování pro specifická okna a TUI rozhraní
      window.commands = [
        { command = "border pixel 3"; criteria = { class = "Alacritty"; }; }
        { command = "floating enable"; criteria = { class = "FloatingTUI"; }; }
        { command = "floating enable, border none, move position center, opacity 0.9"; criteria = { class = "Wlogout"; }; }
        { command = "floating enable, border none, fullscreen enable"; criteria = { instance = "floating_impala"; }; }
        { command = "fullscreen enable"; criteria = { class = "FloatingTerminal"; }; }
        { command = "floating enable, sticky enable, resize set 350 65, move position 15 45, border pixel 4"; criteria = { class = "PomodoroTimer"; }; }
      ];

      # Kompletní klávesové zkratky (Včetně tvého směrového 'uring')
      keybindings = let 
        mod = "Mod4";
      in pkgs.lib.mkOptionDefault {
        "${mod}+Return" = "exec alacritty";
        "${mod}+Shift+q" = "kill";
        "${mod}+Shift+c" = "reload";
        "${mod}+Shift+r" = "restart";
        "${mod}+Shift+e" = "exec ~/scripts_sway/powermenu.sh";
#       "${mod}+Shift+e" = "exec wlogout -l ~/.config/wlogout/layout -b 5";
        "${mod}+Shift+x" = "exec ~/scripts_sway/lock.sh";
        "${mod}+Shift+S" = "exec alacritty -e ssh ratta@100.97.214.64";

        # Skripty a vyhledávací menu
        "${mod}+d" = "exec rofi -show drun";
        #"${mod}+Tab" = "exec python3 ~/.config/i3/scripts/switcher.py";
        "${mod}+g" = "exec ~/scripts_sway/websearch.sh";
        "${mod}+Shift+w" = "exec ~/scripts_sway/pomodoro_toggle.sh";

        # Pohyb a zaměření oken (i3 styl + 'uring')
        "${mod}+j" = "focus left";
        "${mod}+k" = "focus down";
        "${mod}+l" = "focus up";
        "${mod}+odiaeresis" = "focus right"; # ů klávesa na CZ layoutu
        "${mod}+Left" = "focus left";
        "${mod}+Down" = "focus down";
        "${mod}+Up" = "focus up";
        "${mod}+Right" = "focus right";

        # Přesun kontejnerů
        "${mod}+Shift+j" = "move left";
        "${mod}+Shift+k" = "move down";
        "${mod}+Shift+l" = "move up";
        "${mod}+Shift+odiaeresis" = "move right"; # ů klávesa na CZ layoutu
        "${mod}+Shift+Left" = "move left";
        "${mod}+Shift+Down" = "move down";
        "${mod}+Shift+Up" = "move up";
        "${mod}+Shift+Right" = "move right";

        # Správa rozvržení (Layouts)
        "${mod}+h" = "split h";
        "${mod}+v" = "split v";
        "${mod}+f" = "fullscreen toggle";
        "${mod}+s" = "layout stacking";
        "${mod}+w" = "layout tabbed";
        "${mod}+e" = "layout toggle split";
        "${mod}+i" = "floating toggle";
        "${mod}+a" = "focus parent";

        # Multimediální klávesy a HW kontrola jasu/zvuku
        "XF86MonBrightnessUp"   = "exec brightnessctl set +10%";
        "XF86MonBrightnessDown" = "exec brightnessctl set 10%-";
        # Zatím neexistuje
        "XF86AudioRaiseVolume"  = "exec ~/scripts_sway/scripts/volume_notify.sh +5%";
        "XF86AudioLowerVolume"  = "exec ~/scripts_sway/scripts/volume_notify.sh -5%";
        #
        "XF86AudioMute"         = "exec pactl set-sink-mute @DEFAULT_SINK@ toggle";
        "XF86AudioMicMute"      = "exec pactl set-source-mute @DEFAULT_SOURCE@ toggle";
		"Print" = "exec ~/scripts_sway/screenshot.sh";
		"Shift+Print" = "exec ~/scripts_sway/screenshot.sh delay";
      };

      # Barevné schéma oken (Tvůj kontrast žluté a černé)
      colors = {
        focused = {
          border = "#282a36"; background = "#282a36"; text = "#ffffff"; indicator = "#282a36"; childBorder = "#282a36";
        };
        focusedInactive = {
          border = "#000000"; background = "#000000"; text = "#ffffff"; indicator = "#000000"; childBorder = "#000000";
        };
        unfocused = {
          border = "#000000"; background = "#000000"; text = "#ffffff"; indicator = "#000000"; childBorder = "#000000";
        };
        urgent = {
          border = "#ff0000"; background = "#ff0000"; text = "#ffffff"; indicator = "#ff0000"; childBorder = "#ff0000";
        };
      };

      bars = [{
        fonts = {
          names = [ "Ubuntu" ];
          size = 13.0;
        };
        statusCommand = "i3status -c ${config.xdg.configFile."i3status/config".source}";
        position = "bottom";
        extraConfig = ''
          bindsym button1 exec alacritty --class "floating_impala" -e impala
        '';
        colors = {
          background = "#282a36";
          statusline = "#ffffff";
          separator = "#666666";
          focusedWorkspace = {
            border = "#ffffff"; background = "#282a36"; text = "#ffffff";
          };
          activeWorkspace = {
            border = "#282a36"; background = "#282a36"; text = "#ffffff";
          };
          inactiveWorkspace = {
            border = "#282a36"; background = "#282a36"; text = "#ffffff";
          };
          urgentWorkspace = {
            border = "#ff0000"; background = "#ff0000"; text = "#ffffff";
          };
        };
      }];
    };


  };

  # GTK dark téma — správná Nix cesta místo exec v startupe
  gtk = {
    enable = true;
    theme = {
      name = "Adwaita-dark";
      package = pkgs.gnome-themes-extra;
    };
    gtk4.theme = null; # Zamlčí varování o změně výchozí hodnoty gtk4.theme
  };


home.file."scripts_sway/powermenu.sh" = {
  executable = true;
  text = ''
    #!/usr/bin/env bash
    options="Lock\nShutdown\nReboot\nSleep\nLogout\nCancel"

    chosen=$(
      echo -e "$options" | rofi -dmenu \
        -p "Power" \
        -no-custom \
        -lines 6  \
        -theme-str 'listview { scrollbar: false; } inputbar { enabled: false; } listview { lines: 5; } window { width: 18em; }'
    )

    case "$chosen" in
        Lock) bash ~/scripts_sway/lock.sh ;;
        Shutdown) systemctl poweroff ;;
        Reboot) systemctl reboot ;;
        Sleep) systemctl suspend ;;
        Logout) swaymsg exit ;;
        *) exit 0 ;;
    esac
  '';
};

home.file."scripts_sway/lock.sh" = {
  executable = true;
  text = ''
    #!/usr/bin/env bash

    swaylock \
      --screenshots \
      --clock \
      --indicator \
      --indicator-radius 150 \
      --indicator-thickness 13 \
      --effect-blur 7x5 \
      \
      --timestr "%H:%M" \
      --datestr "%A, %d. %B" \
      \
      --font "Ubuntu Bold" \
      --font-size 28 \
      \
      --ring-color f2f2f2 \
      --key-hl-color ffff00 \
      --bs-hl-color ffff00 \
      --inside-color 000000aa \
      --ring-ver-color f2f2f2 \
      --inside-ver-color 000000aa \
      --ring-wrong-color ff0000 \
      --inside-wrong-color f2f2f2 \
      \
      --text-color ffff00 \
      --text-ver-color f2f2f2 \
      --text-wrong-color ff0000
  '';
};

home.file."scripts_sway/screenshot.sh" = {
  executable = true;
  text = ''
    #!/usr/bin/env bash

    case "$1" in
      "delay") sleep 3 && grim -g "$(slurp)" - | wl-copy ;;
      *)       grim -g "$(slurp)" - | wl-copy ;;
    esac
  '';
};

  # Tvoje zachované aliasy
  programs.bash = {
    enable = true;
    shellAliases = {
      nrs = "sudo nixos-rebuild switch --flake .#node1";
      ll = "ls -alh";
      hms = "home-manager switch";
    };
  };

  xdg.configFile."fastfetch/config.jsonc".text = ''
    {
      "modules": ["os", "host", "kernel", "uptime", "shell", "terminal", "cpu", "memory"]
    }
  '';
}
