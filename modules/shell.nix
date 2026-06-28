{ config, pkgs, ... }: {

  programs.bash = {
    enable = true;
    shellAliases = {
      nrs = "sudo nixos-rebuild switch --flake .#node1";
      ll = "ls -alh";
      hms = "home-manager switch";
      bt = "bluetuith";
    };
  };

  xdg.configFile."fastfetch/config.jsonc".text = ''
    {
      "modules": ["os", "host", "kernel", "uptime", "shell", "terminal", "cpu", "memory"]
    }
  '';

}
