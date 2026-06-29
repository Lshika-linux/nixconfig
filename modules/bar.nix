{ config, pkgs, ... }: {

  programs.i3status = {
    enable = true;
    enableDefault = false;
    general = {
      interval = 1;
      colors = true;
      color_good = "#ffffff";
      color_degraded = "#ffff00";
      color_bad = "#ff0000";
    };
    modules = {
      "wireless _first_" = {
        position = 1;
        settings = {
          format_up = "W: (%bitrate %quality at %essid) %ip";
          format_down = "W: down";
        };
      };
      "battery 0" = {
        position = 2;
        settings = {
          format = "PWR/INT: %status %percentage [%remaining]";
          path = "/sys/class/power_supply/BAT0/uevent";
        };
      };
      "battery 1" = {
        position = 3;
        settings = {
          format = "PWR/EXT: %status %percentage [%remaining]";
          path = "/sys/class/power_supply/BAT1/uevent";
        };
      };
      "volume master" = {
        position = 4;
        settings = {
          format = "VOL:    %volume";
          format_muted = "VOL:  MUTED";
          device = "default";
        };
      };
      "load" = {
        position = 5;
        settings = { format = "LOAD:%1min"; };
      };
      "cpu_usage" = {
        position = 6;
        settings = { format = "CPU: %usage"; };
      };
	  "cpu_temperature 0" = {
	    position = 7;
	    settings = {
	      format = "CPUTEMP: %degrees °C";
	      max_threshold = 80;
	      path = "/sys/class/hwmon/hwmon7/temp1_input";
	    };
	  };
      "memory" = {
        position = 8;
        settings = {
          format = "MEM[U/A]: %used/%available";
          threshold_degraded = "1G";
          format_degraded = "MEM < %available";
        };
      };
      "tztime local" = {
        position = 10;
        settings = { format = "%d-%m-%y %H:%M:%S"; };
      };
      "read_file KB" = {
        position = 9;
        settings = {
          path = "/tmp/kb_layout";
          format = "KB: %content";
        };
      };
    };
  };

}
