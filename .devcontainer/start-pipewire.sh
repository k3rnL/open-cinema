#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/pipewire}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# Ensure a D-Bus session bus exists (headless containers usually don't have one)
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
  # Start a private session bus and export env vars into this shell
  eval "$(dbus-launch --sh-syntax)"
fi

# Start services if not already running
pgrep -x pipewire >/dev/null 2>&1 || pipewire &
pgrep -x wireplumber >/dev/null 2>&1 || wireplumber &
pgrep -x pipewire-pulse >/dev/null 2>&1 || pipewire-pulse &

# Readiness check
for i in {1..50}; do
  pw-cli info 0 >/dev/null 2>&1 && break
  sleep 0.1
done

# Optional: verify WP can talk to PW
wpctl status >/dev/null 2>&1 || true
echo "PipeWire + WirePlumber + pipewire-pulse started."