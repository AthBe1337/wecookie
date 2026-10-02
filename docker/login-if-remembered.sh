#!/usr/bin/env bash
set -Eeuo pipefail

export DISPLAY="${DISPLAY:-:99}"
status_script="${STATUS_SCRIPT:-/usr/local/bin/wechat-status}"

status="$($status_script || true)"
window="$(xdotool search --name '^微信$' 2>/dev/null | head -n 1 || true)"
if [[ -n "$window" ]]; then
  geometry="$(xdotool getwindowgeometry "$window")"
  if grep -q 'Geometry: 292x396' <<<"$geometry"; then
    xdotool windowactivate "$window"
    position="$(sed -n 's/.*Position: \([0-9-]*\),\([0-9-]*\).*/\1 \2/p' <<<"$geometry")"
    read -r left top <<<"$position"
    xdotool mousemove "$((left + 146))" "$((top + 308))"
    xdotool click 1
    printf '%s\n' mobile_confirmation
    exit 0
  fi
fi
printf '%s\n' "$status"
