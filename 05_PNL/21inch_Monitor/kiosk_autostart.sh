#!/usr/bin/env bash
set -euo pipefail

URL="${HOME_CONTROL_MONITOR_URL:-http://127.0.0.1:8765/}"
PROFILE="${HOME_CONTROL_CHROMIUM_PROFILE:-${HOME}/.config/chromium-21inch-kiosk}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

for _ in $(seq 1 60); do
    if [[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]]; then
        break
    fi
    sleep 2
done

[[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]] || {
    echo "HomeControl kiosk: Wayland session is not available" >&2
    exit 1
}

for _ in $(seq 1 60); do
    if curl --fail --silent --show-error --connect-timeout 2 "$URL" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

curl --fail --silent --show-error --connect-timeout 2 "$URL" >/dev/null

if pgrep -u "$(id -u)" -x chromium >/dev/null 2>&1 \
        || pgrep -u "$(id -u)" -x chromium-browser >/dev/null 2>&1; then
    exit 0
fi

if command -v chromium >/dev/null 2>&1; then
    browser=chromium
elif command -v chromium-browser >/dev/null 2>&1; then
    browser=chromium-browser
else
    echo "HomeControl kiosk: Chromium is not installed" >&2
    exit 1
fi

exec "$browser" \
    --ozone-platform=wayland \
    --disable-gpu \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-screensaver \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --disable-features=Translate,MediaRouter \
    --password-store=basic \
    --user-data-dir="$PROFILE" \
    "$URL"
