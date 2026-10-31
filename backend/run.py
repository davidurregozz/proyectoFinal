"""Start the local FastAPI server."""

import uvicorn


def main():
    uvicorn.run("backend.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
