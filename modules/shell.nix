{ config, pkgs, ... }: {

  programs.bash = {
    enable = true;
    shellAliases = {
      nrs = "sudo nixos-rebuild switch --flake .#node1";
      ll = "ls -alh";
      hms = "home-manager switch";
      bt = "bluetuith";
      captive-on  = "sudo resolvectl dnsovertls wlan0 no && sudo resolvectl domain wlan0 '' && sudo resolvectl dns wlan0 '' && echo 'DNS unlocked - log in, then run captive-off'";
      captive-off = "sudo systemctl restart systemd-resolved && echo 'DNS locked back down'";
    };
  };

  xdg.configFile."fastfetch/config.jsonc".text = ''
    {
      "modules": ["os", "host", "kernel", "uptime", "shell", "terminal", "cpu", "memory"]
    }
  '';

}
