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
COPY tests ./tests
COPY start.py simulador_buses.py ./

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown app:app /app/data
USER app


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


# Tkinter dashboard; needs an X server reachable through DISPLAY.
FROM base AS dashboard

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
USER app

ENV SIMULADOR_API_URL=http://backend:8000

CMD ["python", "-m", "frontend.run"]
