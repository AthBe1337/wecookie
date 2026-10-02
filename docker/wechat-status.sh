#!/usr/bin/env bash
set -Eeuo pipefail

export DISPLAY="${DISPLAY:-:99}"

windows="$(xdotool search --name '^微信$' 2>/dev/null || true)"
window="$(head -n 1 <<<"$windows")"
if [[ -z "$window" ]]; then
  printf '%s\n' unknown
  exit 2
fi

xdotool windowactivate "$window" 2>/dev/null || true

# Main window geometry differs materially from the login window.
while read -r candidate; do
  [[ -z "$candidate" ]] && continue
  geometry="$(xdotool getwindowgeometry "$candidate" 2>/dev/null || true)"
  if grep -qE 'Geometry: 91[78]x667' <<<"$geometry"; then
    printf '%s\n' logged_in
    exit 0
  fi
done <<<"$windows"

capture="$(mktemp)"
trap 'rm -f "$capture"' EXIT
xwd -display "$DISPLAY" -root -silent -out "$capture"
# The QR region has many dark pixels. Read the first byte of each XWD pixel,
# which is sufficient for the black modules and avoids extra image packages.
qr_pixels="$(dd if="$capture" bs=1 skip=32 2>/dev/null | od -An -tu1 -v \
  | awk 'BEGIN { n=0; i=0 } { for (j=1; j<=NF; j=j+1) { x=$j; col=i%5120; row=int(i/5120); if (col >= 2276 && col < 2844 && row >= 291 && row < 433 && x < 55) n=n+1; i=i+1 } } END { print n+0 }')"
if (( qr_pixels > 1000 )); then
  printf '%s\n' qr
  exit 0
fi

# The remembered-account page has a solid green button at the fixed login
# location. This is deliberately broad because XWD channel order varies.
button_pixels="$(dd if="$capture" bs=1 skip=32 2>/dev/null | od -An -tu1 -v \
  | awk 'BEGIN { n=0; i=0 } { for (j=1; j<=NF; j=j+1) { x=$j; col=i%5120; row=int(i/5120); if (col >= 2208 && col < 2908 && row >= 490 && row < 540 && x > 70 && x < 240) n=n+1; i=i+1 } } END { print n+0 }')"
if (( button_pixels > 1000 )); then
  printf '%s\n' remembered_login
  exit 0
fi

printf '%s\n' mobile_confirmation
exit 0
