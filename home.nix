{ config, pkgs, ... }:

{
  home.username = "rafi";
  home.homeDirectory = "/home/rafi";
  home.stateVersion = "24.11";

  # 1. Tady instalujeme balíčky
  home.packages = with pkgs; [
    swaybg
    wofi
    wlogout
    fastfetch
    kitty
  ];

  # 2. Tady konfigurujeme to, co chceme
  # Službu swaybg.enable a image smaž, ty v HM pro swaybg nefungují takto přímo
  
  programs.home-manager.enable = true;

  programs.kitty = {
      enable = true;
      settings = {
        background_opacity = "0.85";
        font_size = "12.0";
        confirm_os_window_close = 0;
  
        # Tvá paleta z exit.sh
        foreground = "#cdd6f4";
        background = "#1a1e2e";
        cursor     = "#c8848b";
  
        # ANSI barvy (přesně podle barev v tvém swaylock skriptu)
        color0  = "#2e3a59"; # Ring color
        color1  = "#e06060"; # Ring/BS highlight
        color2  = "#5b8dd9"; # Ring ver color
        color3  = "#c8848b"; # Key HL color
        color4  = "#5b8dd9"; # Blue accent
        color5  = "#c8848b"; # Magenta/Accent
        color6  = "#88c0d0"; # Soft cyan
        color7  = "#cdd6f4"; # Text color
      };
  };

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
