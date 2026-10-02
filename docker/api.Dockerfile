FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends x11-utils x11-apps xdotool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY api_server.py /app/api_server.py

ENTRYPOINT ["python3", "/app/api_server.py"]
