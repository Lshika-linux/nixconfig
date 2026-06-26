# configuration.nix - here we declare system level stuff - generally things that require root #

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

  # For disk encryption password in  GUI:
  boot.initrd.systemd.enable = true;

  # CAVE: Connected with the .#node1 alias in home.nix, REQUIRED FOR CORRECT BUILDING!
  # Change both or dont change! 
  networking.hostName = "node1"; 

  # Pure IWD (No NetworkManageru, as god intended)
  networking.wireless.iwd.enable = true;

  # Sets the timezone
  time.timeZone = "Europe/Prague";

  # Select internationalisation properties.
  i18n.defaultLocale = "en_US.UTF-8";

  # Greetd - display manager for the greeter, tuigreet is a TUI login screen
  # Autolaunch sway once loged in
  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = "${pkgs.tuigreet}/bin/tuigreet --time --cmd sway";
      };
    };
  };
  
  # Allows the core of Sway on the system level
  programs.sway = {
    enable = true;
    wrapperFeatures.gtk = true; # For the correct implementation of GTK themes (.. Adwaita..)
  };

  # Portals for screen sharing (Discord/Browser)
  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
    config.common.default = "*";
  };

  # Enable CUPS to print documents.
  services.printing.enable = true;

  # Sound..
  services.pipewire = {
     enable = true;
     pulse.enable = true;
  };
  
  services.libinput.enable = true;

  # USER settings - Rafi
  users.users.rafi = {
     isNormalUser = true;
     extraGroups = [ "wheel" "video" "audio" "input" ];
     packages = with pkgs; [ ];
  };

  # Sys. packages (ideally only basic SW and TUI tools)
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
     impala       # Wi-Fi TUI
     bluetuith    # Bluetooth TUI
     htop
     steam
  ];

  fonts.packages = with pkgs; [
    (nerd-fonts.fira-code)
    (nerd-fonts.hack)
  ];

  # BT..
  hardware.bluetooth.enable = true;
  hardware.bluetooth.powerOnBoot = true;

  # Zakázání trackpointu na systémové úrovni (Sway ho navíc pojistí v home.nix)
  hardware.trackpoint.enable = false;
  
  security.polkit.enable = true;
  services.udisks2.enable = true;
  zramSwap.enable = true;

  # TLP battery setting for the dual battery T480
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
  # CAVE: DONT TOUCH THIS VALUE IF YOU ARENT R E A L L Y SURE YOU WANT TO # 
  system.stateVersion = "24.11";
}
