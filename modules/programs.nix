{ config, pkgs, ... }: {

  programs.kitty = {
    enable = true;
    settings = {
      background_opacity = "0.75";
      font_size = "13.0";
      confirm_os_window_close = 0;
      foreground = "#cdd6f4";
      background = "#1a1e2e";
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

  gtk = {
    enable = true;
    theme = {
      name = "Adwaita-dark";
      package = pkgs.gnome-themes-extra;
    };
    gtk4.theme = null;
  };

}
