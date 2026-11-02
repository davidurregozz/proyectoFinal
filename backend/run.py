"""Start the local FastAPI server."""

import os

import uvicorn

from backend.env import load_env_file


def main():
    load_env_file()
    host = os.environ.get("SIMULADOR_HOST", "127.0.0.1")
    port = int(os.environ.get("SIMULADOR_PORT", "8000"))
    uvicorn.run("backend.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
