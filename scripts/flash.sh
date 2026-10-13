#!/usr/bin/env bash
# Flash a Pro Micro (Caterina bootloader) half of the Sofle with avrdude.
#
# Usage: scripts/flash.sh [path/to/firmware.hex]
#
# Start this first, then tap RST once on the half plugged in over USB. The
# bootloader only lives for ~8s, so the script polls for the new serial port
# and runs avrdude immediately.
#
# macOS: uses /dev/cu.* rather than /dev/tty.* because opening tty.* can block
# waiting for carrier detect.
# Linux: uses /dev/ttyACM*. Your user needs write access (the uucp group on
# Arch/CachyOS, dialout on Debian/Ubuntu), and ModemManager should be told to
# ignore the board -- QMK's udev rules handle both (~/qmk_firmware/util/install_udev.sh).

set -euo pipefail

HEX="${1:-$HOME/qmk_firmware/sofle_rev1_zezking.hex}"
TIMEOUT_SECONDS=300

if [ ! -f "$HEX" ]; then
  echo "Firmware not found: $HEX" >&2
  echo "Build it with: qmk compile -kb sofle/rev1 -km zezking" >&2
  exit 1
fi

case "$(uname -s)" in
  Darwin) PORT_GLOB='/dev/cu.usbmodem*' ;;
  Linux) PORT_GLOB='/dev/ttyACM*' ;;
  *)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

if ! command -v avrdude >/dev/null; then
  echo "avrdude not found. Install it (brew install avrdude / pacman -S avrdude)." >&2
  exit 1
fi

# $PORT_GLOB is intentionally unquoted so the shell expands it.
list_ports() { ls $PORT_GLOB 2>/dev/null || true; }

# Ignore ports that existed before reset so we only pick up the bootloader.
BEFORE="$(list_ports)"

echo "Flashing $HEX"
echo "Waiting for bootloader... tap RST once on the half to flash."

for _ in $(seq 1 $((TIMEOUT_SECONDS * 4))); do
  for PORT in $(list_ports); do
    if ! grep -qxF "$PORT" <<<"$BEFORE"; then
      echo "Found $PORT"
      sleep 0.5
      if [ ! -w "$PORT" ]; then
        echo "No write access to $PORT." >&2
        echo "Add yourself to its group ($(stat -c %G "$PORT" 2>/dev/null || stat -f %Sg "$PORT")) and log back in," >&2
        echo "or install QMK's udev rules: ~/qmk_firmware/util/install_udev.sh" >&2
        exit 1
      fi
      exec avrdude -p atmega32u4 -c avr109 -P "$PORT" -U "flash:w:$HEX:i"
    fi
  done
  sleep 0.25
done

echo "Timed out waiting for bootloader" >&2
exit 1
