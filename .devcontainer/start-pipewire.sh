#!/usr/bin/env bash
set -euo pipefail

runtime_dir="${XDG_RUNTIME_DIR:-/tmp/open-cinema-runtime}"
mkdir -p "${runtime_dir}"
chmod 0700 "${runtime_dir}"

if [[ ! -S "${runtime_dir}/bus" ]]; then
  dbus-daemon \
    --session \
    --fork \
    --address="unix:path=${runtime_dir}/bus" \
    --nopidfile
fi

export XDG_RUNTIME_DIR="${runtime_dir}"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime_dir}/bus"
export PIPEWIRE_REMOTE=pipewire-0

if ! pgrep -u "$(id -u)" -x pipewire >/dev/null 2>&1; then
  pipewire >"${runtime_dir}/pipewire.log" 2>&1 &
fi
if ! pgrep -u "$(id -u)" -x wireplumber >/dev/null 2>&1; then
  wireplumber >"${runtime_dir}/wireplumber.log" 2>&1 &
fi

for _attempt in $(seq 1 100); do
  if pw-cli info 0 >/dev/null 2>&1 && wpctl status >/dev/null 2>&1; then
    exit 0
  fi
  sleep 0.1
done

echo "Isolated PipeWire/WirePlumber startup failed." >&2
tail -n 80 "${runtime_dir}"/*.log >&2 || true
exit 1
