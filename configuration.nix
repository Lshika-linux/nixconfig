# configuration.nix - here we declare system level stuff - generally things that require root #

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

  # For disk encryption password in GUI:
  boot.initrd.systemd.enable = true;

  # CAVE: Connected with the .#node1 alias in home.nix, REQUIRED FOR CORRECT BUILDING!
  # Change both or dont change!
  networking.hostName = "node1";

  # Pure IWD (No NetworkManager, as god intended)
  networking.wireless.iwd = {
    enable = true;
    settings = {
      # iwd handles DHCP + addressing itself, no dhcpcd/networkd needed
      General.EnableNetworkConfiguration = true;
      # Hand DNS to resolved over D-Bus instead of writing resolv.conf.
      # Without this, iwd clobbers resolv.conf via resolvconf and tailscaled
      # ends up with no upstream resolver -> SERVFAIL on everything.
      Network.NameResolvingService = "systemd";
    };
  };
  networking.networkmanager.enable = false;
  networking.useDHCP = false;

  # ..so tailscale doesnt shit itself (split DNS: *.ts.net -> MagicDNS, rest -> Quad9)
  services.resolved = {
    enable = true;

    settings.Resolve = {
      # Quad9 blokuje známé malware/phishing domény přímo na DNS úrovni.
      # #hostname NENÍ komentář - ověřuje se proti němu TLS certifikát!
      DNS = [
        "9.9.9.9#dns.quad9.net"
        "149.112.112.112#dns.quad9.net"
      ];
      FallbackDNS = [
        "9.9.9.9#dns.quad9.net"
        "149.112.112.112#dns.quad9.net"
        "2620:fe::fe#dns.quad9.net"
      ];

      # "~." = routovací doména pro VŠECHNO. Přebije DNS z DHCP,
      # takže cizí router (kavárna, hotel) nemůže unést naše dotazy.
      Domains = [ "~." ];

      DNSOverTLS = "true";
      DNSSEC = "allow-downgrade";
      LLMNR = "false";        # LLMNR poisoning je standardní pentest krok
      MulticastDNS = "no";
    };
  };

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
    package = pkgs.swayfx;
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
  security.rtkit.enable = true;   # lets pipewire get realtime priority (fixes xruns/crackling)
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  services.libinput.enable = true;

  services.tailscale.enable = true;

  # swaylock needs its own PAM entry or it can never unlock
  security.pam.services.swaylock = {};

  # USER settings - Rafi
  users.users.rafi = {
    isNormalUser = true;
    extraGroups = [ "wheel" "video" "audio" "input" "networkmanager" ];
    packages = with pkgs; [ ];
  };

  # Sys. packages (ideally only basic SW and TUI tools)
  environment.systemPackages = with pkgs; [
    (python3.withPackages (ps: with ps; [ i3ipc ]))
    vim
    tree
    wget
    wob          # Volume BAR
    micro
    kitty
    git
    curl
    wl-clipboard
    mc
    librewolf
    udiskie
    kanshi
    grim
    slurp
    imagemagick
    swaylock-effects
    swayidle
    brightnessctl
    firefox
    lxqt.lxqt-policykit
    impala       # Wi-Fi TUI
    bluetuith    # Bluetooth TUI
    htop
    dnsutils     # dig / nslookup - for the next time DNS breaks
  ];

  fonts.packages = with pkgs; [
    (nerd-fonts.fira-code)
    (nerd-fonts.hack)
  ];

  environment.variables = {
    MOZ_ENABLE_WAYLAND = "1";
  };

  # BT..
  hardware.bluetooth.enable = true;
  hardware.bluetooth.powerOnBoot = true;

  # Zakázání trackpointu na systémové úrovni (Sway ho navíc pojistí v home.nix)
  hardware.trackpoint.enable = false;

  hardware.sensor.iio.enable = true;

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
