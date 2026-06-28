#home.nix - here we declare packages for the user layer, generally no root requirement#
# also the home for configs n such.. #


{ config, pkgs, ... }:

{
  imports = [
    ./modules/shell.nix
    ./modules/programs.nix
  ];


  home.username = "rafi";
  home.homeDirectory = "/home/rafi";
  home.stateVersion = "24.11";
  xdg.enable = true;
  	
  # 1. Uživatelské balíčky spravované přes Home Manager
  home.packages = with pkgs; [
    swaybg
    termdown
    obsidian
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

  programs.i3status = {
    enable = true;
	enableDefault = false;
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
	extraConfig = ''
	  workspace number 1
	  titlebar_border_thickness 0
	  titlebar_padding 0 0
	  for_window [all] title_format " "
	  bindsym --to-code Mod4+1 workspace number 1
	  bindsym --to-code Mod4+2 workspace number 2
	  bindsym --to-code Mod4+3 workspace number 3
	  bindsym --to-code Mod4+4 workspace number 4
	  bindsym --to-code Mod4+5 workspace number 5
	  bindsym --to-code Mod4+6 workspace number 6
	  bindsym --to-code Mod4+7 workspace number 7
	  bindsym --to-code Mod4+8 workspace number 8
	  bindsym --to-code Mod4+9 workspace number 9
	  bindsym --to-code Mod4+0 workspace number 10
	  bindsym --to-code Mod4+Shift+1 move container to workspace number 1
	  bindsym --to-code Mod4+Shift+2 move container to workspace number 2
	  bindsym --to-code Mod4+Shift+3 move container to workspace number 3
	  bindsym --to-code Mod4+Shift+4 move container to workspace number 4
	  bindsym --to-code Mod4+Shift+5 move container to workspace number 5
	  bindsym --to-code Mod4+Shift+6 move container to workspace number 6
	  bindsym --to-code Mod4+Shift+7 move container to workspace number 7
	  bindsym --to-code Mod4+Shift+8 move container to workspace number 8
	  bindsym --to-code Mod4+Shift+9 move container to workspace number 9
	  bindsym --to-code Mod4+Shift+0 move container to workspace number 10
	'';
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
		"2:10:TPPS/2_IBM_TrackPoint" = {
		  events = "disabled";
		};
      };

      # Autostart tvých skriptů a démonů na pozadí
      startup = [
        # GTK téma je nastaveno přes gtk.theme níže — exec zde není potřeba
        { command = "libinput-gestures-setup start"; always = false; }
        { command = "gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'"; always = false; }
        { command = "mpv --no-video ~/scripts_sway/meow.mp3"; } # Počáteční mňouknutí
		{ command = "rm -f $SWAYSOCK.wob && mkfifo $SWAYSOCK.wob && tail -f $SWAYSOCK.wob | wob"; }
      ];

      # Nastavení mezer (gaps) a ohraničení oken
      gaps = {
        inner = 2;
        outer = 0;
        smartBorders = "on";
        smartGaps = true;
      };

	  window = {
	    border = 4;
	    titlebar = false;
	  };
	  floating = {
	     border = 4;
	     titlebar = false;
	  };     


      # Pravidla chování pro specifická okna a TUI rozhraní
      window.commands = [
        { command = "border pixel 3"; criteria = { class = "Alacritty"; }; }
        { command = "floating enable"; criteria = { class = "FloatingTUI"; }; }
        { command = "floating enable, border none, move position center, opacity 0.9"; criteria = { class = "Wlogout"; }; }
        { command = "floating enable, border none, fullscreen enable"; criteria = { instance = "floating_impala"; }; }
        { command = "fullscreen enable"; criteria = { class = "FloatingTerminal"; }; }
		{ command = "floating enable, sticky enable, resize set 200 100, move position 1700 25, border pixel 4"; criteria = { app_id = "PomodoroTimer"; }; }
      ];

      # Kompletní klávesové zkratky (Včetně tvého směrového 'uring')
      keybindings = let 
        mod = "Mod4";
      in pkgs.lib.mkOptionDefault {
        "${mod}+Return" = "exec kitty";
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
		"${mod}+t" = "exec ~/scripts_sway/timer.sh";

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
		"XF86AudioRaiseVolume" = "exec pactl set-sink-volume @DEFAULT_SINK@ +5% && pactl get-sink-volume @DEFAULT_SINK@ | grep -oP '\\d+(?=%)' | head -1 | cat > $SWAYSOCK.wob";
		"XF86AudioLowerVolume" = "exec pactl set-sink-volume @DEFAULT_SINK@ -5% && pactl get-sink-volume @DEFAULT_SINK@ | grep -oP '\\d+(?=%)' | head -1 | cat > $SWAYSOCK.wob";
		"XF86AudioMute" = "exec pactl set-sink-mute @DEFAULT_SINK@ toggle";
        "XF86AudioMicMute"      = "exec pactl set-source-mute @DEFAULT_SOURCE@ toggle";
		"Print" = "exec ~/scripts_sway/screenshot.sh";
		"Shift+Print" = "exec ~/scripts_sway/screenshot.sh delay";
      };

      colors = {
        focused = {
          border = "#ffffff"; background = "#ffffff"; text = "#ffffff"; indicator = "#ffffff"; childBorder = "#ffffff";
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
          bindsym button1 exec kitty --class "FloatingTerminal" -e impala
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


home.file."scripts_sway/powermenu.sh" = {
  executable = true;
  text = ''
    #!/usr/bin/env bash
    options="Lock\nShutdown\nReboot\nSleep\nLogout"

    chosen=$(
      echo -e "$options" | rofi -dmenu \
        -p "Power" \
        -no-custom \
        -lines 5  \
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
      --ring-color ffffff \
      --key-hl-color ffffff \
      --bs-hl-color ffffff \
      --inside-color 000000aa \
      --ring-ver-color ffffff \
      --inside-ver-color 000000aa \
      --ring-wrong-color ff0000 \
      --inside-wrong-color f2f2f2 \
      \
      --text-color ffffff \
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

home.file."scripts_sway/timer.sh" = {
  executable = true;
  text = ''
    #!/usr/bin/env bash
    mins=$(echo "" | rofi -dmenu -p "⏱ Timer:" -l 0 -theme-str 'window { location: north; anchor: north; width: 200px; y-offset: 20; border: 2px; border-color: #ffffff; border-radius: 8px; }')
    [ -n "$mins" ] && alacritty --class PomodoroTimer -e termdown "$mins"m
  '';
};


home.file.".config/wob/wob.ini".text = ''
  timeout = 1000
  anchor = right center
  margin = 20
  width = 30
  height = 600
  orientation = vertical
  border_offset = 0
  border_size = 2
  bar_padding = 2
  
  [style.default]
  background_color = 000000AA
  border_color = FFFFFFFF
  bar_color = FFFFFFFF
'';

home.file."scripts_sway/meow.mp3".source = ./sounds/meow.mp3;
home.file."scripts_sway/minecraftcat.mp3".source = ./sounds/minecraftcat.mp3;



home.file.".config/rofi/config.rasi".text = ''
  configuration {
    modi: "drun,run";
    show-icons: true;
    drun-display-format: "{name}";
    font: "Ubuntu Bold 13";
    columns: 2;
  }

  @theme "/dev/null"

  * {
    background-color: #1a1e2e;
    text-color: #ffffff;
    border-color: #ffffff;
  }

  window {
    width: 400px;
    border: 2px;
    border-radius: 8px;
    padding: 10px;
  }

  inputbar {
    padding: 8px;
    margin-bottom: 8px;
    border: 1px;
    border-color: #5b8dd9;
    border-radius: 4px;
  }

  prompt {
    text-color: #5b8dd9;
    margin-right: 8px;
  }

  element {
    padding: 6px 8px;
    border-radius: 4px;
  }

  element selected {
    background-color: #5b8dd9;
    text-color: #1a1e2e;
  }

  element-text {
    background-color: transparent;
    text-color: inherit;
  }

  element-icon {
    size: 20px;
    background-color: transparent;
  }
'';

home.file.".local/share/mc/skins/dracula.ini".text = ''
  [skin]
  description = Dracula

  [core]
  _default_=white;#1a1e2e
  selected=white;#313244
  marked=#f1fa8c;#1a1e2e
  markselect=#f1fa8c;#313244
  gauge=#cdd6f4;#1a1e2e
  input=#cdd6f4;#313244
  inputmark=#1a1e2e;#cdd6f4
  inputunchanged=#6272a4;#1a1e2e
  commandlinemark=#1a1e2e;#cdd6f4
  reverse=#1a1e2e;#cdd6f4
  header=#5b8dd9;#1a1e2e
  disabled=#6272a4;#1a1e2e
  focus=#1a1e2e;#5b8dd9
  dfocus=#cdd6f4;#313244
  shadfocus=#1a1e2e;#5b8dd9
  border=#5b8dd9;#1a1e2e
  
  [dialog]
  _default_=#cdd6f4;#313244
  dsel=#1a1e2e;#5b8dd9
  dfocus=#1a1e2e;#5b8dd9
  dtitle=#5b8dd9;#313244

  [error]
  _default_=#cdd6f4;#ff5555
  errdfocus=#1a1e2e;#ff5555
  errdtitle=white;#ff5555

  [menu]
  _default_=#cdd6f4;#313244
  menusel=#1a1e2e;#5b8dd9
  menutitle=#5b8dd9;#1a1e2e
  menuhotkey=#ff5555;#313244
  menusel=#1a1e2e;#5b8dd9

  [popupmenu]
  _default_=#cdd6f4;#313244
  title=#5b8dd9;#313244
  selected=#1a1e2e;#5b8dd9

  [statusbar]
  _default_=#cdd6f4;#1a1e2e

  [buttonbar]
  button=#1a1e2e;#5b8dd9
  hotkey=#1a1e2e;#c8848b

# i dont want any double lines, poor solution, but if it works im to lazy to care
  [Lines]
  horiz = ─
  vert = │
  lefttop = ┌
  righttop = ┐
  leftbottom = └
  rightbottom = ┘
  topmiddle = ┬
  bottommiddle = ┴
  leftmiddle = ├
  rightmiddle = ┤
  cross = ┼
  dhoriz = ─
  dvert = │
  dlefttop = ┌
  drighttop = ┐
  dleftbottom = └
  drightbottom = ┘
'';

home.file.".config/mc/ini".text = ''
  [Midnight-Commander]
  skin=dracula
'';
}
