"""Start the Tkinter desktop dashboard."""

from backend.env import load_env_file
from frontend.dashboard import Simulador


def main():
    load_env_file()
    Simulador().mainloop()


if __name__ == "__main__":
    main()
