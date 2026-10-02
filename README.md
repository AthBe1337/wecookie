# WeChat container login smoke test

This runs the official ARM64 Linux WeChat client under Xvfb/Fluxbox and exposes
a small HTTP API. The API and proxy are separate containers; the API shares the
X11 socket with the WeChat container so it can read the QR screen and perform
the configured link click.

详细 HTTP 接口说明见 [docs/API.md](docs/API.md)。

Build and start:

```sh
cd ~/Soft/wecookie
docker compose build
docker compose up -d
docker compose logs -f wechat
```

The proxy captures `wx.weiweixiao.net` by default, matching the current pinned
link. Override `TARGET_DOMAINS` with a comma-separated domain list if the link
changes. The API listens on port 8090. Set `API_TOKEN` to require
`Authorization: Bearer ...`.

```sh
API_TOKEN=local-token docker compose up -d --build
curl -H 'Authorization: Bearer local-token' http://127.0.0.1:8090/api/status
curl -H 'Authorization: Bearer local-token' http://127.0.0.1:8090/api/qr -o qr.png
curl -H 'Authorization: Bearer local-token' http://127.0.0.1:8090/api/cookie
```

`/api/cookie` activates the logged-in WeChat window, opens the configured pinned
chat (`PINNED_CHAT_X,PINNED_CHAT_Y`), then clicks the latest link at
(`OPEN_LINK_X,OPEN_LINK_Y`). It waits for mitmproxy to observe a matching
request, waits for matching traffic to settle (`COOKIE_SETTLE_SECONDS`, 3 seconds
by default), and writes the latest Cookie JSON into the `cookie-data` named
volume. If the browser reuses an unchanged Cookie header, the API waits up to
`COOKIE_REUSE_WAIT` (6 seconds by default) and returns the last captured value
instead of treating that as a timeout. The coordinates must match the fixed
desktop layout in the container.

The WeChat container has no published desktop port. For an initial login, take a screenshot
from the virtual display after the login window appears:

```sh
docker exec wecookie-wechat-test bash -lc \
  'xwd -display :99 -root -silent -out /tmp/screens/root.xwd'
docker cp wecookie-wechat-test:/tmp/screens/root.xwd /tmp/root.xwd
ffmpeg -y -f xwd_pipe -i /tmp/root.xwd -frames:v 1 ./root.png
```

The named volume `wechat-home` contains the WeChat profile and is retained when
the container is recreated. `cookie-data` contains the latest captured Cookie.
