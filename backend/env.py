"""Load optional settings from the project's .env file when running without Docker."""

import os
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path=ENV_PATH):
    """Set KEY=value pairs from .env; variables already in the environment win."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip("\"'")
        if name and value and not os.environ.get(name):
            os.environ[name] = value
