#!/usr/bin/env bash
# Flash a Pro Micro (Caterina bootloader) half of the Sofle with avrdude.
#
# Usage: scripts/flash.sh [path/to/firmware.hex]
#
# Start this first, then tap RST once on the half plugged in over USB. The
# bootloader only lives for ~8s, so the script polls for the new serial port
# and runs avrdude immediately. It uses /dev/cu.* rather than /dev/tty.*
# because opening tty.* on macOS can block waiting for carrier detect.

set -euo pipefail

HEX="${1:-$HOME/qmk_firmware/sofle_rev1_zezking.hex}"
TIMEOUT_SECONDS=300

if [ ! -f "$HEX" ]; then
  echo "Firmware not found: $HEX" >&2
  echo "Build it with: qmk compile -kb sofle/rev1 -km zezking" >&2
  exit 1
fi

list_ports() { ls /dev/cu.usbmodem* 2>/dev/null || true; }

# Ignore ports that existed before reset so we only pick up the bootloader.
BEFORE="$(list_ports)"

echo "Flashing $HEX"
echo "Waiting for bootloader... tap RST once on the half to flash."

for _ in $(seq 1 $((TIMEOUT_SECONDS * 4))); do
  for PORT in $(list_ports); do
    if ! grep -qxF "$PORT" <<<"$BEFORE"; then
      echo "Found $PORT"
      sleep 0.5
      exec avrdude -p atmega32u4 -c avr109 -P "$PORT" -U "flash:w:$HEX:i"
    fi
  done
  sleep 0.25
done

echo "Timed out waiting for bootloader" >&2
exit 1
