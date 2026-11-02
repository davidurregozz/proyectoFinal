FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY start.py simulador_buses.py ./

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown app:app /app/data
USER app


# Unit tests: docker compose --profile test run --rm tests
FROM base AS test

COPY --chown=app:app tests ./tests

CMD ["python", "-m", "unittest", "discover", "tests"]


# REST API with SQLite stored in /app/data.
FROM base AS backend

ENV SIMULADOR_HOST=0.0.0.0 \
    SIMULADOR_PORT=8000 \
    SIMULADOR_DB_PATH=/app/data/simulador.sqlite3

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["python", "-m", "backend.run"]


# Tkinter dashboard drawn on the host X server given in DISPLAY.
# The slim image strips the Tk runtime, so it is installed here.
FROM base AS dashboard

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends tk fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
USER app

ENV SIMULADOR_API_URL=http://backend:8000

CMD ["python", "-m", "frontend.run"]


# Same dashboard on a virtual display, viewed in the browser through noVNC.
FROM dashboard AS dashboard-web

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb x11vnc openbox novnc websockify \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && printf '%s\n' \
        '<!doctype html><meta charset="utf-8">' \
        '<meta http-equiv="refresh" content="0; url=vnc.html?autoconnect=true&resize=scale&reconnect=true">' \
        > /usr/share/novnc/index.html
COPY docker/dashboard-web.sh /usr/local/bin/dashboard-web
RUN sed -i 's/\r$//' /usr/local/bin/dashboard-web \
    && chmod 755 /usr/local/bin/dashboard-web
USER app

ENV DISPLAY=:99 \
    SCREEN_RESOLUTION=1440x900x24 \
    NOVNC_PORT=6080

EXPOSE 6080

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6080/vnc.html', timeout=2)"

CMD ["dashboard-web"]
