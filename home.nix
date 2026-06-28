#home.nix - here we declare packages for the user layer, generally no root requirement#
# also the home for configs n such.. #


{ config, pkgs, ... }:

{
  imports = [
    ./modules/shell.nix  			# Contains aliases
    ./modules/programs.nix			# Contains programs.kitty, GTK settings for some reason, clarify?
    ./modules/bar.nix				# Contains i3status config
    ./modules/sway.nix				# Contains sway enviroment config
    ./modules/scripts.nix			# Contains screenshot.sh, powermenu.sh,..
  ];


  home.username = "rafi";
  home.homeDirectory = "/home/rafi";
  home.stateVersion = "24.11";
  xdg.enable = true;
  	
  # 1. Uživatelské balíčky spravované přes Home Manager
  home.packages = with pkgs; [
    swaybg
    termdown
	xkblayout-state
    obsidian
    fastfetch
    alacritty
    rofi                # rofi-wayland byl sloučen zpět do rofi
    i3status
    blanket             # Pro zkratku $mod+B
    libinput-gestures
    inter               # Inter font použitý v sway config (font pango:Inter)
    ubuntu-classic      # Ubuntu font pro bar (dříve ubuntu_font_family)
    mpv                 # Pro meow.mp3 při startu
    gnome-themes-extra  # Pro Adwaita-dark GTK téma
  ];

}
