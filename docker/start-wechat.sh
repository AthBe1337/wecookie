#!/usr/bin/env bash
set -Eeuo pipefail

export DISPLAY="${DISPLAY:-:99}"
export SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1280x800x24}"
export HOME=/home/wechat
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-wechat}"
export LANG="${LANG:-zh_CN.UTF-8}"
export LC_ALL="${LC_ALL:-zh_CN.UTF-8}"
# Xvfb has no hardware renderer. Force software GL and X11 platform so the
# embedded Chromium runtime does not probe unavailable Wayland/DRM devices.
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export EGL_PLATFORM="${EGL_PLATFORM:-x11}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-x11}"

mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# Trust mitmproxy's persistent CA in Chromium's per-user NSS database when the
# proxy sidecar has generated it. This avoids changing the host trust store.
proxy_ca=/mitmproxy-state/mitmproxy/mitmproxy-ca-cert.pem
for _ in $(seq 1 30); do
  if [[ -r "$proxy_ca" ]]; then
    mkdir -p "$HOME/.pki/nssdb"
    if ! certutil -d "sql:$HOME/.pki/nssdb" -L 2>/dev/null \
      | grep -q 'mitmproxy-local'; then
      timeout 5 certutil -d "sql:$HOME/.pki/nssdb" -N --empty-password \
        </dev/null >/dev/null 2>&1 || true
      timeout 5 certutil -d "sql:$HOME/.pki/nssdb" -A -n mitmproxy-local -t 'C,,' \
        -i "$proxy_ca" >/dev/null 2>&1 || true
    fi
    break
  fi
  sleep 1
done

# A previous crash can leave Xvfb's display lock behind. The container owns
# this display, so remove only the lock/socket for :99 before starting it.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

Xvfb "$DISPLAY" -screen 0 "$SCREEN_GEOMETRY" -ac -nolisten tcp +extension GLX +render -noreset \
  >/tmp/xvfb.log 2>&1 &
xvfb_pid=$!

cleanup() {
  kill "$xvfb_pid" 2>/dev/null || true
  rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 50); do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
xdpyinfo -display "$DISPLAY" >/dev/null

fluxbox >/tmp/fluxbox.log 2>&1 &

dbus-run-session -- wechat \
  --disable-gpu \
  --disable-gpu-compositing \
  "$@" &
wechat_pid=$!

# Give a remembered account a chance to reach the main window after restart.
# A QR page or mobile confirmation is left untouched for the HTTP/status layer.
for _ in $(seq 1 60); do
  status="$(/usr/local/bin/wechat-status 2>/dev/null || true)"
  case "$status" in
    logged_in|mobile_confirmation)
      break
      ;;
    qr)
      # The small login window is also used for a remembered account. The
      # fixed button click is harmless on a QR page and enables auto-login.
      /usr/local/bin/login-if-remembered >/tmp/login-if-remembered.log 2>&1 || true
      break
      ;;
    remembered_login)
      /usr/local/bin/login-if-remembered >/tmp/login-if-remembered.log 2>&1 || true
      break
      ;;
  esac
  sleep 1
done

wait "$wechat_pid"
