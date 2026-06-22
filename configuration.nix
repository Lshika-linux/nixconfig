# Edit this configuration file to define what should be installed on
# your system.
# Help is available in the configuration.nix(5) man page, on
# https://search.nixos.org/options and in the NixOS manual (`nixos-help`).

{ config, lib, pkgs, ... }:

{
  imports =
    [ # Include the results of the hardware scan.
      ./hardware-configuration.nix
    ];

  # Use the systemd-boot EFI boot loader.
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.plymouth.enable = true;
  
  # Pro to, aby se heslo k disku zadávalo v GUI:
  boot.initrd.systemd.enable = true;
  
  # Sjednoceno s tvým aliasem .#node1 v home.nix, aby flake správně buildoval
  networking.hostName = "node1"; 

  # Připojení k síti přes čisté IWD (bez NetworkManageru)
  networking.wireless.iwd.enable = true;

  # Set your time zone.
  time.timeZone = "Europe/Prague";

  # Select internationalisation properties.
  i18n.defaultLocale = "en_US.UTF-8";

  # Povolení správce přihlášení (greetd) s automatickým startem do Swaye
  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = "${pkgs.tuigreet}/bin/tuigreet --time --cmd sway";
      };
    };
  };

  # Povolení jádra Swaye na systémové úrovni
  programs.sway = {
    enable = true;
    wrapperFeatures.gtk = true; # Správné načítání GTK témat (např. Adwaita)
  };

  # Portály pro bezproblémové sdílení obrazovky (např. v Discordu/prohlížeči)
  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
    config.common.default = "*";
  };

  # Enable CUPS to print documents.
  services.printing.enable = true;

  # Moderní zvukový server PipeWire
  services.pipewire = {
     enable = true;
     pulse.enable = true;
  };
  
  services.libinput.enable = true;

  # Nastavení uživatele Rafi
  users.users.rafi = {
     isNormalUser = true;
     extraGroups = [ "wheel" "video" "audio" "input" ];
     packages = with pkgs; [ ];
  };

  # Systémové balíčky (Zde zůstává jen základní softwarová výbava a TUI nástroje)
  environment.systemPackages = with pkgs; [
     vim 
     wget
     micro
     kitty
     git
     curl
     wl-clipboard
     udiskie
     kanshi
     grim
     slurp
     swaylock-effects
     swayidle
     brightnessctl
     firefox
     flameshot
     lxqt.lxqt-policykit
     impala       # Tvoje Wi-Fi TUI
     bluetuith    # Tvoje Bluetooth TUI
     htop
     steam
  ];

  fonts.packages = with pkgs; [
    (nerd-fonts.fira-code)
    (nerd-fonts.hack)
  ];

  hardware.bluetooth.enable = true;
  hardware.bluetooth.powerOnBoot = true;

  # Zakázání trackpointu na systémové úrovni (Sway ho navíc pojistí v home.nix)
  hardware.trackpoint.enable = false;
  
  security.polkit.enable = true;
  services.udisks2.enable = true;
  zramSwap.enable = true;

  # TLP nastavení baterie pro tvůj Lenovo notebook
  services.tlp = {
    enable = true;
    settings = {
      START_CHARGE_THRESH_BAT0 = 40;
      STOP_CHARGE_THRESH_BAT0 = 80;
      START_CHARGE_THRESH_BAT1 = 40;
      STOP_CHARGE_THRESH_BAT1 = 80;
    };
  };
  
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  nixpkgs.config.allowUnfree = true;

  programs.dconf.enable = true;

  system.stateVersion = "24.11";
}
