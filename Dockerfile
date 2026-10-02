FROM ubuntu:24.04

ARG WECHAT_DEB_URL=https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_arm64.deb

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    XDG_RUNTIME_DIR=/tmp/runtime-wechat \
    QT_X11_NO_MITSHM=1

RUN sed -i 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.aliyun.com/ubuntu-ports|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       dbus-x11 \
       fluxbox \
       fonts-noto-cjk \
       libasound2t64 \
       libatk-bridge2.0-0 \
       libatk1.0-0 \
       libatspi2.0-0 \
       libavahi-client3 \
       libavahi-common3 \
       libcairo2 \
       libcups2t64 \
       libdrm2 \
       libgbm1 \
       libnss3 \
       libpango-1.0-0 \
       libpangocairo-1.0-0 \
       libudev1 \
       libxcomposite1 \
       libxdamage1 \
       libxfixes3 \
       libxkbcommon0 \
       libxrandr2 \
       locales \
       x11-apps \
       x11-utils \
       x11-xserver-utils \
       xdotool \
       xvfb \
    && locale-gen zh_CN.UTF-8 \
    && curl -fL --retry 3 -o /tmp/wechat.deb "$WECHAT_DEB_URL" \
    && apt-get install -y /tmp/wechat.deb \
    && rm -f /tmp/wechat.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.aliyun.com/ubuntu-ports|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       libatomic1 \
       libegl1 \
       libepoxy0 \
       libgtk-3-0 \
       libnss3-tools \
       libpulse0 \
       libwayland-client0 \
       libwayland-cursor0 \
       libwayland-egl1 \
       libxkbcommon-x11-0 \
       libxss1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1001 --shell /bin/bash wechat \
    && mkdir -p /tmp/runtime-wechat \
    && mkdir -p /tmp/screens \
    && mkdir -p /home/wechat/.fluxbox \
    && printf '%s\n' \
       'session.styleFile: /usr/share/fluxbox/styles/Operation' \
       'session.screen0.rootCommand: xsetroot -solid black' \
       > /home/wechat/.fluxbox/init \
    && chown -R wechat:wechat /tmp/runtime-wechat /tmp/screens /home/wechat

COPY --chmod=0755 docker/start-wechat.sh /usr/local/bin/start-wechat
COPY --chmod=0755 docker/wechat-status.sh /usr/local/bin/wechat-status
COPY --chmod=0755 docker/login-if-remembered.sh /usr/local/bin/login-if-remembered

USER wechat
WORKDIR /home/wechat

ENTRYPOINT ["/usr/local/bin/start-wechat"]
