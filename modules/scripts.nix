{ config, pkgs, ... }: {

home.file."scripts_sway/powermenu.py" = {
  executable = true;
  source = ../modules/powermenu.py;
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

home.file."scripts_sway/timer.py" = {
  executable = true;
  source = ../modules/timer.py;
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

home.file."scripts_sway/meow.mp3".source = ../sounds/meow.mp3;
home.file."scripts_sway/minecraftcat.mp3".source = ../sounds/minecraftcat.mp3;


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

home.file."scripts_sway/kb_layout.sh" = {
  executable = true;
  text = ''
    #!/usr/bin/env bash
    
    update_layout() {
      new=$(swaymsg -t get_inputs | python3 -c "
import json,sys
inputs = json.load(sys.stdin)
for i in inputs:
    l = i.get(\"xkb_active_layout_name\",\"\")
    if l:
        print(\"CZE\" if \"Czech\" in l else \"ENG\")
        break
")
      current=$(cat /tmp/kb_layout 2>/dev/null)
      if [ "$new" != "$current" ]; then
        echo "$new" > /tmp/kb_layout.tmp && mv /tmp/kb_layout.tmp /tmp/kb_layout
      fi
    }
    
    update_layout
    swaymsg -t subscribe '["input"]' --monitor | while read -r _; do
      update_layout
    done
  '';
};

home.file."scripts_sway/switcher.py" = {
  executable = true;
  source = ../modules/switcher.py;
};

home.file."scripts_sway/launcher.py" = {
  executable = true;
  source = ../modules/launcher.py;
};

home.file."scripts_sway/connectivity.py" = {
  executable = true;
  source = ../modules/connectivity.py;
};

home.file."scripts_sway/raficalendar.py" = {
  executable = true;
  source = ../modules/raficalendar.py;
};

}
