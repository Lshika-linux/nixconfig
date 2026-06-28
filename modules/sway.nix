{ config, pkgs, ... }:

{
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
          bg = "${../wallpapers/wallpaper.png} fill";
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
}
