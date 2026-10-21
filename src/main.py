from simulador import SimuladorCore
from interfaz import SimuladorGUI

if __name__ == "__main__":
    core = SimuladorCore()
    app = SimuladorGUI(core)
    app.mainloop()