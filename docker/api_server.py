#!/usr/bin/env python3
import base64
import io
import json
import logging
import os
import re
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DISPLAY = os.environ.get("DISPLAY", ":99")
API_TOKEN = os.environ.get("API_TOKEN", "")
COOKIE_FILE = Path(os.environ.get("COOKIE_FILE", "/data/latest-cookie.json"))
PINNED_CHAT_X = int(os.environ.get("PINNED_CHAT_X", "350"))
PINNED_CHAT_Y = int(os.environ.get("PINNED_CHAT_Y", "185"))
OPEN_LINK_X = int(os.environ.get("OPEN_LINK_X", "700"))
OPEN_LINK_Y = int(os.environ.get("OPEN_LINK_Y", "238"))
WINDOW_HIDE_DELAY = float(os.environ.get("WINDOW_HIDE_DELAY", "0.5"))
FOCUS_DELAY = float(os.environ.get("FOCUS_DELAY", "0.8"))
CHAT_OPEN_DELAY = float(os.environ.get("CHAT_OPEN_DELAY", "1.5"))
COOKIE_TIMEOUT = float(os.environ.get("COOKIE_TIMEOUT", "20"))
COOKIE_SETTLE_SECONDS = float(os.environ.get("COOKIE_SETTLE_SECONDS", "3.0"))
COOKIE_REUSE_WAIT = float(os.environ.get("COOKIE_REUSE_WAIT", "6.0"))
MAIN_WINDOW_WIDTH = int(os.environ.get("MAIN_WINDOW_WIDTH", "917"))
MAIN_WINDOW_HEIGHT = int(os.environ.get("MAIN_WINDOW_HEIGHT", "667"))
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800
capture_lock = threading.Lock()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wecookie.api")


def run(*args):
    return subprocess.run(args, env={**os.environ, "DISPLAY": DISPLAY},
                          text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=False).stdout


def windows():
    ids = run("xdotool", "search", "--name", "^微信$").split()
    result = []
    for wid in ids:
        geometry = run("xdotool", "getwindowgeometry", wid)
        match = re.search(r"Position: ([-0-9]+),([-0-9]+).*Geometry: (\d+)x(\d+)", geometry, re.S)
        if match:
            result.append({"id": int(wid), "x": int(match.group(1)), "y": int(match.group(2)),
                           "width": int(match.group(3)), "height": int(match.group(4))})
    return result


def main_window(items=None):
    """Select the fixed-size main window, not an embedded browser popup."""
    candidates = [item for item in (items or windows())
                  if item["width"] >= 900 and item["height"] >= 650]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item["width"] - MAIN_WINDOW_WIDTH)
               + abs(item["height"] - MAIN_WINDOW_HEIGHT))


def state():
    items = windows()
    if main_window(items) is not None:
        return "logged_in"
    if not items:
        return "unknown"
    if any(item["width"] == 292 and item["height"] == 396 for item in items):
        # The small window covers QR, remembered-account, and mobile-confirmation.
        # The API exposes this as login_required until a button action changes it.
        return "login_required"
    return "unknown"


def click_login():
    for item in windows():
        if item["width"] == 292 and item["height"] == 396:
            env = {**os.environ, "DISPLAY": DISPLAY}
            subprocess.run(["xdotool", "windowactivate", str(item["id"])], env=env,
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["xdotool", "mousemove", str(item["x"] + 146),
                            str(item["y"] + 308), "click", "1"], env=env, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


def capture_xwd():
    with tempfile.NamedTemporaryFile(prefix="wechat-", suffix=".xwd") as handle:
        subprocess.run(["xwd", "-display", DISPLAY, "-root", "-silent", "-out", handle.name],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return Path(handle.name).read_bytes()


def xwd_to_png(xwd):
    if len(xwd) < 100:
        raise ValueError("invalid XWD")
    header = struct.unpack(">25I", xwd[:100])
    header_size, width, height = header[0], header[4], header[5]
    bits_per_pixel, bytes_per_line, ncolors = header[11], header[12], header[19]
    if bits_per_pixel not in (24, 32):
        raise ValueError("unsupported XWD format")
    pixel_stride = bits_per_pixel // 8
    if bytes_per_line < width * pixel_stride:
        raise ValueError("unsupported XWD stride")
    data_offset = header_size + ncolors * 12
    rows = []
    for y in range(height):
        row = bytearray([0])
        pixels = xwd[data_offset + y * bytes_per_line:data_offset + (y + 1) * bytes_per_line]
        for offset in range(0, width * pixel_stride, pixel_stride):
            b, g, r = pixels[offset:offset + 3]
            row.extend((r, g, b))
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


def write_json(handler, value, status=HTTPStatus.OK):
    payload = json.dumps(value, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def authorized(self):
        if not API_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {API_TOKEN}"

    def do_GET(self):
        if not self.authorized():
            write_json(self, {"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            write_json(self, {"state": state(), "windows": windows(), "updated_at": time.time()})
        elif path == "/api/qr":
            if state() == "logged_in":
                write_json(self, {"error": "already_logged_in"}, HTTPStatus.CONFLICT)
                return
            try:
                payload = xwd_to_png(capture_xwd())
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                write_json(self, {"error": "screen_capture_failed", "detail": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif path == "/api/cookie":
            self.get_cookie()
        else:
            write_json(self, {"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self.authorized():
            write_json(self, {"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        path = urlparse(self.path).path
        if path == "/api/login":
            if click_login():
                write_json(self, {"state": "mobile_confirmation"})
            else:
                write_json(self, {"state": state()}, HTTPStatus.CONFLICT)
        elif path == "/api/cookie":
            self.get_cookie()
        else:
            write_json(self, {"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def get_cookie(self):
        if state() != "logged_in":
            write_json(self, {"error": "wechat_not_logged_in", "state": state()}, HTTPStatus.CONFLICT)
            return
        with capture_lock:
            before = COOKIE_FILE.stat().st_mtime_ns if COOKIE_FILE.exists() else 0
            windows_now = windows()
            target = main_window(windows_now)
            if target is None:
                write_json(self, {"error": "wechat_main_window_missing"}, HTTPStatus.CONFLICT)
                return
            logger.info("cookie capture start target_window=%s windows=%s before_mtime=%s",
                        target["id"], [(item["id"], item["width"], item["height"])
                                       for item in windows_now], before)
            env = {**os.environ, "DISPLAY": DISPLAY}
            # A previous link can leave an embedded browser over the chat list.
            # Minimize those windows so the fixed chat coordinates reach WeChat.
            for item in windows_now:
                if item["id"] != target["id"]:
                    result = subprocess.run(["xdotool", "windowminimize", str(item["id"])], env=env,
                                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    logger.info("minimize window=%s rc=%s", item["id"], result.returncode)
            time.sleep(WINDOW_HIDE_DELAY)
            result = subprocess.run(["xdotool", "windowactivate", str(target["id"])], env=env,
                                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("activate window=%s rc=%s", target["id"], result.returncode)
            time.sleep(FOCUS_DELAY)
            result = subprocess.run(["xdotool", "mousemove", str(PINNED_CHAT_X),
                                     str(PINNED_CHAT_Y), "click", "1"], env=env, check=False,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("click pinned_chat=(%s,%s) rc=%s",
                        PINNED_CHAT_X, PINNED_CHAT_Y, result.returncode)
            time.sleep(CHAT_OPEN_DELAY)
            result = subprocess.run(["xdotool", "mousemove", str(OPEN_LINK_X),
                                     str(OPEN_LINK_Y), "click", "1"], env=env, check=False,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("click latest_link=(%s,%s) rc=%s",
                        OPEN_LINK_X, OPEN_LINK_Y, result.returncode)
            deadline = time.monotonic() + min(
                COOKIE_TIMEOUT, COOKIE_REUSE_WAIT if before else COOKIE_TIMEOUT
            )
            observed_mtime = before
            last_change_at = None
            while time.monotonic() < deadline:
                if COOKIE_FILE.exists():
                    current_mtime = COOKIE_FILE.stat().st_mtime_ns
                    if current_mtime > before and current_mtime != observed_mtime:
                        observed_mtime = current_mtime
                        last_change_at = time.monotonic()
                        logger.info("cookie file updated mtime=%s", current_mtime)
                if (last_change_at is not None
                        and time.monotonic() - last_change_at >= COOKIE_SETTLE_SECONDS):
                    try:
                        value = json.loads(COOKIE_FILE.read_text())
                    except (OSError, json.JSONDecodeError):
                        value = {"cookie": COOKIE_FILE.read_text(errors="replace")}
                    write_json(self, value)
                    return
                time.sleep(0.25)
        # A browser may reuse an unchanged Cookie header, so mitmproxy has no
        # file event to report even though the page was opened successfully.
        # Reuse the last captured value when one is available; only report a
        # timeout when there has never been a capture.
        if COOKIE_FILE.exists():
            try:
                value = json.loads(COOKIE_FILE.read_text())
            except (OSError, json.JSONDecodeError):
                value = {"cookie": COOKIE_FILE.read_text(errors="replace")}
            logger.info("cookie unchanged; returning existing capture")
            write_json(self, value)
            return
        logger.warning("cookie capture timed out timeout=%ss settle=%ss",
                       COOKIE_TIMEOUT, COOKIE_SETTLE_SECONDS)
        write_json(self, {"error": "cookie_capture_timeout"}, HTTPStatus.GATEWAY_TIMEOUT)


if __name__ == "__main__":
    port = int(os.environ.get("HTTP_PORT", "8090"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
